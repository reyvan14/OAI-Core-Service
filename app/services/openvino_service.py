"""
OpenVINO LLM 服务

提供基于 Intel OpenVINO 的 LLM 模型下载、转换和推理功能
"""

import os
import logging
import time
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# 检查 OpenVINO 相关依赖
try:
    from optimum.intel import OVModelForCausalLM
    from transformers import AutoTokenizer, TextIteratorStreamer
    from threading import Thread
    OPENVINO_AVAILABLE = True
except ImportError:
    OPENVINO_AVAILABLE = False
    logger.warning("OpenVINO 相关库未安装，OpenVINO 功能将不可用")


class OpenVINOService:
    """OpenVINO LLM 服务"""

    def __init__(self, models_dir: str = "./models/openvino"):
        """
        初始化 OpenVINO 服务

        Args:
            models_dir: 模型存储目录
        """
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.download_tasks = {}  # 下载任务状态
        self.loaded_models = {}  # 已加载的模型缓存
        self.executor = ThreadPoolExecutor(max_workers=2)

        logger.info(f"OpenVINO Service initialized. Models dir: {self.models_dir}")

    def is_available(self) -> bool:
        """检查 OpenVINO 是否可用"""
        return OPENVINO_AVAILABLE

    async def download_and_convert_model(
        self,
        model_id: str,
        device: str = "CPU",
        precision: str = "INT8",
        task_id: Optional[str] = None
    ) -> str:
        """
        下载并转换 HuggingFace 模型为 OpenVINO IR 格式

        Args:
            model_id: HuggingFace 模型ID, 如 "Qwen/Qwen-7B-Chat"
            device: 目标设备 (CPU, GPU, AUTO)
            precision: 精度 (FP32, FP16, INT8, INT4)
            task_id: 任务ID

        Returns:
            模型保存路径
        """
        if not self.is_available():
            raise RuntimeError("OpenVINO 库未安装")

        # 生成任务ID
        if task_id is None:
            task_id = f"{model_id.replace('/', '_')}_{int(time.time())}"

        # 更新任务状态
        self.download_tasks[task_id] = {
            "status": "pending",
            "progress": 0,
            "message": "准备下载模型...",
            "started_at": datetime.now()
        }

        # 在后台执行下载和转换
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._download_and_convert_sync,
            model_id, device, precision, task_id
        )

        return task_id

    def _download_and_convert_sync(
        self,
        model_id: str,
        device: str,
        precision: str,
        task_id: str
    ):
        """同步下载和转换（在后台线程执行）"""
        try:
            # 1. 下载阶段
            self.download_tasks[task_id].update({
                "status": "downloading",
                "progress": 10,
                "message": f"正在从 HuggingFace 下载 {model_id}..."
            })

            logger.info(f"Downloading model: {model_id}")

            # 生成模型保存路径
            model_name = model_id.replace("/", "_")
            save_path = self.models_dir / f"{model_name}_{device}_{precision}"

            # 2. 转换阶段
            self.download_tasks[task_id].update({
                "status": "converting",
                "progress": 50,
                "message": f"正在转换为 OpenVINO IR 格式 ({precision})..."
            })

            logger.info(f"Converting model to OpenVINO IR: {model_id} -> {save_path}")

            # 使用 optimum-intel 导出模型
            # 配置量化参数
            quantization_config = None
            if precision == "INT8":
                # INT8 量化配置
                from optimum.intel import OVConfig, OVQuantizationConfig
                quantization_config = OVQuantizationConfig(bits=8)
            elif precision == "INT4":
                from optimum.intel import OVConfig, OVQuantizationConfig
                quantization_config = OVQuantizationConfig(bits=4)

            # 导出模型
            model = OVModelForCausalLM.from_pretrained(
                model_id,
                export=True,  # 自动导出为 OpenVINO IR
                compile=False,  # 先不编译，保存后再加载
                quantization_config=quantization_config,
                cache_dir=str(self.models_dir / "cache"),
                device=device
            )

            # 保存模型
            model.save_pretrained(str(save_path))

            # 下载 tokenizer
            tokenizer = AutoTokenizer.from_pretrained(
                model_id,
                cache_dir=str(self.models_dir / "cache")
            )
            tokenizer.save_pretrained(str(save_path))

            # 3. 完成
            self.download_tasks[task_id].update({
                "status": "completed",
                "progress": 100,
                "message": "模型下载和转换完成",
                "model_path": str(save_path),
                "completed_at": datetime.now()
            })

            logger.info(f"Model conversion completed: {save_path}")

        except Exception as e:
            logger.error(f"Model download/conversion failed: {e}", exc_info=True)
            self.download_tasks[task_id].update({
                "status": "failed",
                "progress": 0,
                "message": f"失败: {str(e)}",
                "error": str(e),
                "failed_at": datetime.now()
            })

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取下载任务状态"""
        return self.download_tasks.get(task_id)

    def list_models(self) -> List[Dict[str, Any]]:
        """列出已下载的模型"""
        models = []

        if not self.models_dir.exists():
            return models

        for model_dir in self.models_dir.iterdir():
            if model_dir.is_dir() and (model_dir / "openvino_model.xml").exists():
                # 读取配置
                config_path = model_dir / "config.json"
                size_mb = sum(f.stat().st_size for f in model_dir.rglob('*') if f.is_file()) / (1024 * 1024)

                # 解析模型信息
                name_parts = model_dir.name.split("_")
                device = name_parts[-2] if len(name_parts) >= 2 else "CPU"
                precision = name_parts[-1] if len(name_parts) >= 1 else "FP32"

                models.append({
                    "model_id": model_dir.name,
                    "model_name": "_".join(name_parts[:-2]),
                    "model_path": str(model_dir),
                    "device": device,
                    "precision": precision,
                    "size_mb": round(size_mb, 2),
                    "created_at": datetime.fromtimestamp(model_dir.stat().st_mtime)
                })

        return sorted(models, key=lambda x: x["created_at"], reverse=True)

    def delete_model(self, model_path: str) -> bool:
        """删除模型"""
        try:
            path = Path(model_path)
            if path.exists() and path.is_dir():
                # 如果模型已加载，先卸载
                if model_path in self.loaded_models:
                    del self.loaded_models[model_path]

                # 删除目录
                shutil.rmtree(path)
                logger.info(f"Model deleted: {model_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete model: {e}")
            return False

    def load_model(self, model_path: str, device: str = "CPU"):
        """加载模型到内存"""
        if not self.is_available():
            raise RuntimeError("OpenVINO 库未安装")

        # 检查缓存
        cache_key = f"{model_path}_{device}"
        if cache_key in self.loaded_models:
            logger.info(f"Using cached model: {model_path}")
            return self.loaded_models[cache_key]

        # 加载模型
        logger.info(f"Loading model: {model_path} on {device}")
        start_time = time.time()

        model = OVModelForCausalLM.from_pretrained(
            model_path,
            device=device,
            compile=True  # 编译模型以优化推理
        )

        tokenizer = AutoTokenizer.from_pretrained(model_path)

        load_time = time.time() - start_time
        logger.info(f"Model loaded in {load_time:.2f}s")

        # 缓存模型
        self.loaded_models[cache_key] = {
            "model": model,
            "tokenizer": tokenizer,
            "loaded_at": datetime.now()
        }

        return self.loaded_models[cache_key]

    async def generate_text(
        self,
        model_path: str,
        prompt: str,
        device: str = "CPU",
        max_tokens: int = 100,
        temperature: float = 0.7,
        stream: bool = False
    ) -> Dict[str, Any]:
        """
        生成文本

        Args:
            model_path: 模型路径
            prompt: 输入提示词
            device: 设备
            max_tokens: 最大生成token数
            temperature: 温度参数
            stream: 是否流式生成

        Returns:
            生成结果
        """
        if not self.is_available():
            raise RuntimeError("OpenVINO 库未安装")

        try:
            # 加载模型
            model_data = self.load_model(model_path, device)
            model = model_data["model"]
            tokenizer = model_data["tokenizer"]

            # Tokenize 输入
            inputs = tokenizer(prompt, return_tensors="pt")

            # 记录开始时间
            start_time = time.time()
            first_token_time = None

            # 生成配置
            gen_kwargs = {
                "max_new_tokens": max_tokens,
                "do_sample": temperature > 0,
                "temperature": temperature if temperature > 0 else None,
                "pad_token_id": tokenizer.eos_token_id,
            }

            # 生成
            if stream:
                # 流式生成（暂时不实现，返回完整结果）
                outputs = model.generate(**inputs, **gen_kwargs)
            else:
                outputs = model.generate(**inputs, **gen_kwargs)

            # 第一个 token 延迟（估算）
            if first_token_time is None:
                first_token_time = time.time()

            # 解码输出
            generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

            # 计算性能指标
            total_time = time.time() - start_time
            generated_tokens = len(outputs[0]) - len(inputs["input_ids"][0])
            tokens_per_second = generated_tokens / total_time if total_time > 0 else 0
            first_token_latency = first_token_time - start_time

            return {
                "success": True,
                "generated_text": generated_text,
                "tokens_per_second": round(tokens_per_second, 2),
                "first_token_latency": round(first_token_latency, 3),
                "total_time": round(total_time, 3),
                "generated_tokens": generated_tokens
            }

        except Exception as e:
            logger.error(f"Text generation failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }


# 全局单例
openvino_service = OpenVINOService()
