"""
智能表单处理系统

核心功能：
1. 表单识别与分类 - 智能识别表单类型和结构
2. 字段提取与验证 - 自动提取字段并验证完整性
3. 智能填写建议 - 基于用户历史和上下文的填写建议
4. 合规性检查 - 业务规则和合规性验证
5. 多模态处理 - 支持文本、图像等多种输入格式
"""

import logging
import json
import re
import uuid
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import asyncio

from app.services.llm_service import LLMService
from app.models.request import UserRequest
from app.utils.security import InputValidator, sanitize_filename, validate_file_path

logger = logging.getLogger(__name__)


class FormType(Enum):
    """表单类型枚举"""
    EXPENSE_REPORT = "expense_report"      # 报销单
    LEAVE_REQUEST = "leave_request"        # 请假条
    PROCUREMENT = "procurement"            # 采购申请
    TRAVEL_APPLICATION = "travel_application"  # 出差申请
    OVERTIME_REQUEST = "overtime_request"  # 加班申请
    PERFORMANCE_REVIEW = "performance_review"  # 绩效评估
    EQUIPMENT_REQUEST = "equipment_request"  # 设备申请
    TRAINING_APPLICATION = "training_application"  # 培训申请
    GENERAL_FORM = "general_form"          # 通用表单


class FieldType(Enum):
    """字段类型枚举"""
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    EMAIL = "email"
    PHONE = "phone"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    TEXTAREA = "textarea"
    FILE = "file"
    CURRENCY = "currency"
    SIGNATURE = "signature"


class ValidationStatus(Enum):
    """验证状态"""
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    WARNING = "warning"


@dataclass
class FormField:
    """表单字段定义"""
    field_id: str
    field_name: str
    field_type: FieldType
    label: str
    required: bool = True
    placeholder: Optional[str] = None
    options: List[str] = field(default_factory=list)  # 用于select、radio、checkbox
    validation_rules: Dict[str, Any] = field(default_factory=dict)
    default_value: Optional[str] = None
    description: Optional[str] = None
    group: Optional[str] = None  # 字段分组


@dataclass
class FormFieldValue:
    """表单字段值"""
    field_id: str
    value: Any
    confidence: float = 1.0  # 识别或提取的置信度
    source: str = "manual"  # manual, extraction, suggestion
    validation_status: ValidationStatus = ValidationStatus.PENDING
    validation_errors: List[str] = field(default_factory=list)


@dataclass
class FormDefinition:
    """表单定义"""
    form_id: str
    form_type: FormType
    form_name: str
    version: str = "1.0"
    fields: List[FormField] = field(default_factory=list)
    workflow_rules: Dict[str, Any] = field(default_factory=dict)
    approval_requirements: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class FormInstance:
    """表单实例"""
    instance_id: str
    form_definition: FormDefinition
    field_values: Dict[str, FormFieldValue] = field(default_factory=dict)
    status: str = "draft"  # draft, submitted, approved, rejected
    submitter_id: str = ""
    approver_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    attachments: List[str] = field(default_factory=list)


class FormTemplateManager:
    """表单模板管理器"""

    def __init__(self):
        self.templates = self._initialize_templates()

    def _initialize_templates(self) -> Dict[FormType, FormDefinition]:
        """初始化表单模板"""
        templates = {}

        # 报销单模板
        expense_report_fields = [
            FormField("employee_name", "employee_name", FieldType.TEXT, "姓名", required=True),
            FormField("department", "department", FieldType.SELECT, "部门",
                     required=True, options=["财务部", "技术部", "市场部", "人事部", "行政部"]),
            FormField("expense_type", "expense_type", FieldType.SELECT, "费用类型",
                     required=True, options=["交通费", "住宿费", "餐费", "办公费", "其他"]),
            FormField("amount", "amount", FieldType.CURRENCY, "金额", required=True),
            FormField("expense_date", "expense_date", FieldType.DATE, "费用日期", required=True),
            FormField("description", "description", FieldType.TEXTAREA, "费用说明", required=True),
            FormField("receipt_count", "receipt_count", FieldType.NUMBER, "票据数量", required=False),
            FormField("approver", "approver", FieldType.SELECT, "审批人",
                     options=["部门经理", "财务经理"], required=False)
        ]

        templates[FormType.EXPENSE_REPORT] = FormDefinition(
            form_id="expense_report_v1",
            form_type=FormType.EXPENSE_REPORT,
            form_name="费用报销单",
            fields=expense_report_fields
        )

        # 请假条模板
        leave_request_fields = [
            FormField("employee_name", "employee_name", FieldType.TEXT, "姓名", required=True),
            FormField("leave_type", "leave_type", FieldType.SELECT, "请假类型",
                     required=True, options=["事假", "病假", "年假", "婚假", "产假"]),
            FormField("start_date", "start_date", FieldType.DATETIME, "开始时间", required=True),
            FormField("end_date", "end_date", FieldType.DATETIME, "结束时间", required=True),
            FormField("leave_days", "leave_days", FieldType.NUMBER, "请假天数", required=True),
            FormField("reason", "reason", FieldType.TEXTAREA, "请假原因", required=True),
            FormField("emergency_contact", "emergency_contact", FieldType.PHONE, "紧急联系人", required=False),
            FormField("work_handover", "work_handover", FieldType.TEXTAREA, "工作交接", required=True)
        ]

        templates[FormType.LEAVE_REQUEST] = FormDefinition(
            form_id="leave_request_v1",
            form_type=FormType.LEAVE_REQUEST,
            form_name="请假申请单",
            fields=leave_request_fields
        )

        # 出差申请模板
        travel_fields = [
            FormField("employee_name", "employee_name", FieldType.TEXT, "姓名", required=True),
            FormField("destination", "destination", FieldType.TEXT, "出差地点", required=True),
            FormField("start_date", "start_date", FieldType.DATE, "开始日期", required=True),
            FormField("end_date", "end_date", FieldType.DATE, "结束日期", required=True),
            FormField("travel_days", "travel_days", FieldType.NUMBER, "出差天数", required=True),
            FormField("purpose", "purpose", FieldType.TEXTAREA, "出差目的", required=True),
            FormField("transportation", "transportation", FieldType.SELECT, "交通方式",
                     options=["飞机", "火车", "汽车", "其他"], required=False),
            FormField("budget_estimate", "budget_estimate", FieldType.CURRENCY, "预算估算", required=True),
            FormField("hotel_required", "hotel_required", FieldType.CHECKBOX, "需要住宿", required=False)
        ]

        templates[FormType.TRAVEL_APPLICATION] = FormDefinition(
            form_id="travel_application_v1",
            form_type=FormType.TRAVEL_APPLICATION,
            form_name="出差申请单",
            fields=travel_fields
        )

        return templates

    def get_template(self, form_type: FormType) -> Optional[FormDefinition]:
        """获取表单模板"""
        return self.templates.get(form_type)

    def get_all_templates(self) -> List[FormDefinition]:
        """获取所有模板"""
        return list(self.templates.values())

    def add_template(self, form_definition: FormDefinition):
        """添加新模板"""
        self.templates[form_definition.form_type] = form_definition


class FormValidator:
    """表单验证器"""

    def __init__(self):
        self.validation_rules = self._initialize_validation_rules()

    def _initialize_validation_rules(self) -> Dict[FieldType, Dict[str, Any]]:
        """初始化验证规则"""
        return {
            FieldType.TEXT: {
                "min_length": 1,
                "max_length": 500,
                "pattern": None
            },
            FieldType.NUMBER: {
                "min_value": None,
                "max_value": None,
                "required": True
            },
            FieldType.CURRENCY: {
                "min_value": 0,
                "max_value": 999999,
                "precision": 2
            },
            FieldType.EMAIL: {
                "pattern": r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
                "required": True
            },
            FieldType.PHONE: {
                "pattern": r'^1[3-9]\d{9}$|^0\d{2,3}-?\d{7,8}$',
                "required": True
            },
            FieldType.DATE: {
                "format": "YYYY-MM-DD",
                "required": True
            },
            FieldType.DATETIME: {
                "format": "YYYY-MM-DD HH:MM",
                "required": True
            }
        }

    async def validate_field(self, field: FormField, value: Any) -> Tuple[ValidationStatus, List[str]]:
        """验证单个字段"""
        errors = []

        # 检查必填字段
        if field.required and (value is None or value == ""):
            errors.append(f"{field.label}为必填项")
            return ValidationStatus.INVALID, errors

        if value is None or value == "":
            return ValidationStatus.VALID, errors

        # 根据字段类型进行验证
        if field.field_type == FieldType.TEXT:
            errors.extend(self._validate_text_field(field, value))
        elif field.field_type == FieldType.NUMBER:
            errors.extend(self._validate_number_field(field, value))
        elif field.field_type == FieldType.CURRENCY:
            errors.extend(self._validate_currency_field(field, value))
        elif field.field_type == FieldType.EMAIL:
            errors.extend(self._validate_email_field(field, value))
        elif field.field_type == FieldType.PHONE:
            errors.extend(self._validate_phone_field(field, value))
        elif field.field_type == FieldType.DATE:
            errors.extend(self._validate_date_field(field, value))
        elif field.field_type == FieldType.DATETIME:
            errors.extend(self._validate_datetime_field(field, value))

        # 自定义验证规则
        errors.extend(self._validate_custom_rules(field, value))

        # 确定验证状态
        if errors:
            return ValidationStatus.INVALID, errors
        else:
            return ValidationStatus.VALID, []

    def _validate_text_field(self, field: FormField, value: str) -> List[str]:
        """验证文本字段"""
        errors = []
        rules = self.validation_rules.get(FieldType.TEXT, {})

        if not isinstance(value, str):
            errors.append(f"{field.label}必须是文本")
            return errors

        if "min_length" in field.validation_rules:
            min_length = field.validation_rules["min_length"]
            if len(value) < min_length:
                errors.append(f"{field.label}长度不能少于{min_length}个字符")

        if "max_length" in field.validation_rules:
            max_length = field.validation_rules["max_length"]
            if len(value) > max_length:
                errors.append(f"{field.label}长度不能超过{max_length}个字符")

        if "pattern" in field.validation_rules:
            pattern = field.validation_rules["pattern"]
            if not re.match(pattern, value):
                errors.append(f"{field.label}格式不正确")

        return errors

    def _validate_number_field(self, field: FormField, value: Union[str, int, float]) -> List[str]:
        """验证数字字段"""
        errors = []

        try:
            num_value = float(value)
        except (ValueError, TypeError):
            errors.append(f"{field.label}必须是数字")
            return errors

        if "min_value" in field.validation_rules:
            min_value = field.validation_rules["min_value"]
            if num_value < min_value:
                errors.append(f"{field.label}不能小于{min_value}")

        if "max_value" in field.validation_rules:
            max_value = field.validation_rules["max_value"]
            if num_value > max_value:
                errors.append(f"{field.label}不能大于{max_value}")

        return errors

    def _validate_currency_field(self, field: FormField, value: Union[str, int, float]) -> List[str]:
        """验证货币字段"""
        errors = []

        try:
            # 移除货币符号和逗号
            if isinstance(value, str):
                value = re.sub(r'[¥$,，,]', '', value)

            num_value = float(value)
            if num_value < 0:
                errors.append(f"{field.label}不能为负数")

            if "max_value" in field.validation_rules:
                max_value = field.validation_rules["max_value"]
                if num_value > max_value:
                    errors.append(f"{field.label}不能超过{max_value}")

        except (ValueError, TypeError):
            errors.append(f"{field.label}必须是有效的金额")

        return errors

    def _validate_email_field(self, field: FormField, value: str) -> List[str]:
        """验证邮箱字段"""
        errors = []
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

        if not re.match(pattern, value):
            errors.append(f"{field.label}格式不正确")

        return errors

    def _validate_phone_field(self, field: FormField, value: str) -> List[str]:
        """验证电话字段"""
        errors = []

        # 支持手机号和固话
        phone_pattern = r'^1[3-9]\d{9}$|^0\d{2,3}-?\d{7,8}$'

        if not re.match(phone_pattern, value):
            errors.append(f"{field.label}格式不正确，请输入有效的手机号或固话")

        return errors

    def _validate_date_field(self, field: FormField, value: str) -> List[str]:
        """验证日期字段"""
        errors = []

        try:
            # 支持多种日期格式
            date_formats = ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]
            parsed = False

            for fmt in date_formats:
                try:
                    datetime.strptime(value, fmt)
                    parsed = True
                    break
                except ValueError:
                    continue

            if not parsed:
                errors.append(f"{field.label}格式不正确，请使用YYYY-MM-DD格式")

        except Exception:
            errors.append(f"{field.label}格式不正确")

        return errors

    def _validate_datetime_field(self, field: FormField, value: str) -> List[str]:
        """验证日期时间字段"""
        errors = []

        try:
            # 支持多种日期时间格式
            datetime_formats = [
                "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M",
                "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"
            ]
            parsed = False

            for fmt in datetime_formats:
                try:
                    datetime.strptime(value, fmt)
                    parsed = True
                    break
                except ValueError:
                    continue

            if not parsed:
                errors.append(f"{field.label}格式不正确，请使用YYYY-MM-DD HH:MM格式")

        except Exception:
            errors.append(f"{field.label}格式不正确")

        return errors

    def _validate_custom_rules(self, field: FormField, value: Any) -> List[str]:
        """验证自定义规则"""
        errors = []

        # 业务规则验证
        if field.field_id == "expense_date":
            # 报销日期不能是未来
            try:
                expense_date = datetime.strptime(str(value), "%Y-%m-%d")
                if expense_date > datetime.now():
                    errors.append("费用日期不能是未来日期")
            except ValueError:
                pass

        elif field.field_id == "end_date" and value:
            # 结束日期必须晚于开始日期
            try:
                end_date = datetime.strptime(str(value), "%Y-%m-%d")
                if end_date <= datetime.now():
                    errors.append("结束日期必须晚于当前日期")
            except ValueError:
                pass

        return errors


class IntelligentFormProcessor:
    """智能表单处理器"""

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service
        self.template_manager = FormTemplateManager()
        self.validator = FormValidator()
        self.form_instances = {}  # 存储表单实例

    async def recognize_form(self, content: str, user_context: Dict[str, Any]) -> Tuple[FormType, float]:
        """识别表单类型"""
        try:
            recognition_prompt = f"""
            请分析以下文本内容，识别表单类型：

            文本内容：{content}
            用户信息：{json.dumps(user_context, ensure_ascii=False)}

            请从以下类型中选择最匹配的表单类型：
            - expense_report: 费用报销单
            - leave_request: 请假申请单
            - travel_application: 出差申请单
            - procurement: 采购申请单
            - overtime_request: 加班申请单
            - performance_review: 绩效评估表
            - equipment_request: 设备申请单
            - training_application: 培训申请单
            - general_form: 通用表单

            返回JSON格式：
            {{
                "form_type": "表单类型",
                "confidence": 0.0-1.0,
                "reasoning": "识别理由",
                "keywords": ["关键词1", "关键词2"]
            }}
            """

            result = await self.llm_service.chat_completion([
                {"role": "system", "content": "你是一个专业的表单识别助手，擅长从文本中识别表单类型。"},
                {"role": "user", "content": recognition_prompt}
            ])

            if result.get("success"):
                response_text = result.get("response", "{}")
                try:
                    recognition_data = json.loads(response_text)
                    form_type = FormType(recognition_data.get("form_type", "general_form"))
                    confidence = recognition_data.get("confidence", 0.0)
                    reasoning = recognition_data.get("reasoning", "")

                    logger.info(f"表单识别完成: {form_type.value}, 置信度: {confidence}")
                    return form_type, confidence

                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning(f"表单识别结果解析失败: {e}")

            # 降级到关键词匹配
            return self._fallback_form_recognition(content), 0.6

        except Exception as e:
            logger.error(f"表单识别失败: {e}")
            return FormType.GENERAL_FORM, 0.1

    def _fallback_form_recognition(self, content: str) -> FormType:
        """降级表单识别：基于关键词匹配"""
        content_lower = content.lower()

        # 定义关键词映射
        form_keywords = {
            FormType.EXPENSE_REPORT: ["报销", "费用", "金额", "票据", "交通费", "住宿费"],
            FormType.LEAVE_REQUEST: ["请假", "休假", "事假", "病假", "年假", "请假条"],
            FormType.TRAVEL_APPLICATION: ["出差", "旅行", "目的地", "交通", "住宿"],
            FormType.PROCUREMENT: ["采购", "购买", "供应商", "物品", "设备"],
            FormType.OVERTIME_REQUEST: ["加班", "超时", "工作时间", "加班费"],
            FormType.PERFORMANCE_REVIEW: ["绩效", "评估", "考核", "目标", "KPI"],
            FormType.EQUIPMENT_REQUEST: ["设备", "申领", "工具", "办公用品"],
            FormType.TRAINING_APPLICATION: ["培训", "学习", "课程", "技能"]
        }

        # 计算每种表单类型的关键词匹配分数
        scores = {}
        for form_type, keywords in form_keywords.items():
            score = sum(1 for keyword in keywords if keyword in content_lower)
            if score > 0:
                scores[form_type] = score

        if scores:
            # 返回分数最高的表单类型
            best_form_type = max(scores.keys(), key=lambda x: scores[x])
            logger.info(f"关键词匹配识别: {best_form_type.value}")
            return best_form_type
        else:
            return FormType.GENERAL_FORM

    async def create_form_instance(self, form_type: FormType, user_context: Dict[str, Any]) -> FormInstance:
        """创建表单实例"""
        # 获取表单模板
        template = self.template_manager.get_template(form_type)
        if not template:
            raise ValueError(f"未找到表单类型 {form_type.value} 的模板")

        # 创建表单实例
        instance = FormInstance(
            instance_id=str(uuid.uuid4()),
            form_definition=template,
            submitter_id=user_context.get("user_id", ""),
            status="draft"
        )

        # 预填充一些字段
        await self._prefill_fields(instance, user_context)

        # 保存实例
        self.form_instances[instance.instance_id] = instance

        logger.info(f"创建表单实例: {instance.instance_id}, 类型: {form_type.value}")
        return instance

    async def _prefill_fields(self, instance: FormInstance, user_context: Dict[str, Any]):
        """预填充字段"""
        for field in instance.form_definition.fields:
            # 基于用户信息预填充
            if field.field_id == "employee_name" and "user_name" in user_context:
                field_value = FormFieldValue(
                    field_id=field.field_id,
                    value=user_context["user_name"],
                    source="prefill",
                    confidence=1.0
                )
                instance.field_values[field.field_id] = field_value

            elif field.field_id == "department" and "department" in user_context:
                field_value = FormFieldValue(
                    field_id=field.field_id,
                    value=user_context["department"],
                    source="prefill",
                    confidence=1.0
                )
                instance.field_values[field.field_id] = field_value

            # 基于角色预填充审批人
            elif field.field_id == "approver" and "manager_name" in user_context:
                field_value = FormFieldValue(
                    field_id=field.field_id,
                    value=user_context["manager_name"],
                    source="suggestion",
                    confidence=0.8
                )
                instance.field_values[field.field_id] = field_value

    async def extract_field_values(self, content: str, form_instance: FormInstance) -> Dict[str, FormFieldValue]:
        """从内容中提取字段值"""
        extracted_values = {}

        try:
            # 构建提取提示
            field_descriptions = []
            for field in form_instance.form_definition.fields:
                field_desc = {
                    "field_id": field.field_id,
                    "field_name": field.field_name,
                    "field_type": field.field_type.value,
                    "label": field.label,
                    "required": field.required,
                    "options": field.options if field.field_type in [FieldType.SELECT, FieldType.RADIO, FieldType.CHECKBOX] else []
                }
                field_descriptions.append(field_desc)

            extraction_prompt = f"""
            请从以下文本中提取表单字段值：

            文本内容：{content}
            表单类型：{form_instance.form_definition.form_name}
            字段定义：{json.dumps(field_descriptions, ensure_ascii=False)}

            请返回JSON格式的提取结果：
            {{
                "extracted_values": {{
                    "field_id": {{
                        "value": "提取的值",
                        "confidence": 0.0-1.0,
                        "source": "extracted"
                    }}
                }},
                "missing_fields": ["field_id1", "field_id2"],
                "confidence": 0.0-1.0
            }}

            注意：
            1. 只提取明确提到的字段值
            2. 对于日期格式，请转换为YYYY-MM-DD格式
            3. 对于金额，请转换为数字格式
            4. 如果字段值不明确，请勿提取
            """

            result = await self.llm_service.chat_completion([
                {"role": "system", "content": "你是一个专业的表单信息提取助手，擅长从文本中准确提取表单字段值。"},
                {"role": "user", "content": extraction_prompt}
            ])

            if result.get("success"):
                response_text = result.get("response", "{}")
                try:
                    extraction_data = json.loads(response_text)
                    extracted_data = extraction_data.get("extracted_values", {})

                    # 转换为FormFieldValue对象
                    for field_id, field_data in extracted_data.items():
                        field_value = FormFieldValue(
                            field_id=field_id,
                            value=field_data.get("value"),
                            confidence=field_data.get("confidence", 0.5),
                            source="extraction"
                        )
                        extracted_values[field_id] = field_value

                    logger.info(f"字段提取完成，提取到 {len(extracted_values)} 个字段")

                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"字段提取结果解析失败: {e}")

        except Exception as e:
            logger.error(f"字段提取失败: {e}")

        return extracted_values

    async def generate_filling_suggestions(self, form_instance: FormInstance, user_context: Dict[str, Any]) -> Dict[str, Any]:
        """生成填写建议"""
        suggestions = {}

        try:
            # 分析已填写字段
            filled_fields = [fv for fv in form_instance.field_values.values() if fv.value]
            missing_fields = []

            for field in form_instance.form_definition.fields:
                if field.field_id not in form_instance.field_values or not form_instance.field_values[field.field_id].value:
                    missing_fields.append(field)

            if not missing_fields:
                return {"message": "所有字段已填写完毕", "suggestions": []}

            # 生成填写建议
            suggestion_prompt = f"""
            基于用户上下文和已填写信息，为缺失字段生成填写建议：

            表单类型：{form_instance.form_definition.form_name}
            用户信息：{json.dumps(user_context, ensure_ascii=False)}
            已填写字段：{json.dumps([{fv.field_id: fv.value for fv in filled_fields}], ensure_ascii=False)}
            缺失字段：{json.dumps([{"field_id": f.field_id, "label": f.label, "field_type": f.field_type.value, "required": f.required} for f in missing_fields], ensure_ascii=False)}

            请返回JSON格式：
            {{
                "suggestions": [
                    {{
                        "field_id": "字段ID",
                        "suggested_value": "建议值",
                        "reasoning": "建议理由",
                        "confidence": 0.0-1.0
                    }}
                ]
            }}
            """

            result = await self.llm_service.chat_completion([
                {"role": "system", "content": "你是一个专业的表单填写助手，擅长根据上下文信息为表单字段提供合理的填写建议。"},
                {"role": "user", "content": suggestion_prompt}
            ])

            if result.get("success"):
                response_text = result.get("response", "{}")
                try:
                    suggestion_data = json.loads(response_text)
                    suggestions_list = suggestion_data.get("suggestions", [])

                    for suggestion in suggestions_list:
                        field_id = suggestion.get("field_id")
                        if field_id:
                            suggestions[field_id] = {
                                "value": suggestion.get("suggested_value"),
                                "reasoning": suggestion.get("reasoning", ""),
                                "confidence": suggestion.get("confidence", 0.5)
                            }

                    logger.info(f"生成填写建议完成，建议数量: {len(suggestions)}")

                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"填写建议解析失败: {e}")

        except Exception as e:
            logger.error(f"生成填写建议失败: {e}")

        return suggestions

    async def validate_form(self, form_instance: FormInstance) -> Dict[str, Any]:
        """验证表单"""
        validation_results = {}
        overall_status = ValidationStatus.VALID
        all_errors = []

        # 验证每个字段
        for field in form_instance.form_definition.fields:
            field_value_obj = form_instance.field_values.get(field.field_id)
            value = field_value_obj.value if field_value_obj else None

            status, errors = await self.validator.validate_field(field, value)

            # 更新字段验证状态
            if field_value_obj:
                field_value_obj.validation_status = status
                field_value_obj.validation_errors = errors

            validation_results[field.field_id] = {
                "status": status.value,
                "errors": errors,
                "value": value
            }

            if status == ValidationStatus.INVALID:
                overall_status = ValidationStatus.INVALID
            elif status == ValidationStatus.WARNING and overall_status == ValidationStatus.VALID:
                overall_status = ValidationStatus.WARNING

            all_errors.extend([f"{field.label}: {error}" for error in errors])

        # 业务规则验证
        business_errors = await self._validate_business_rules(form_instance)
        all_errors.extend(business_errors)
        if business_errors:
            overall_status = ValidationStatus.INVALID

        return {
            "overall_status": overall_status.value,
            "field_validations": validation_results,
            "errors": all_errors,
            "is_valid": overall_status == ValidationStatus.VALID
        }

    async def _validate_business_rules(self, form_instance: FormInstance) -> List[str]:
        """验证业务规则"""
        errors = []

        form_type = form_instance.form_definition.form_type

        if form_type == FormType.EXPENSE_REPORT:
            # 报销单业务规则
            amount_value = form_instance.field_values.get("amount")
            if amount_value and amount_value.value:
                try:
                    amount = float(amount_value.value)
                    expense_type = form_instance.field_values.get("expense_type")

                    # 不同费用类型的金额限制
                    if expense_type and expense_type.value:
                        if expense_type.value == "交通费" and amount > 1000:
                            errors.append("交通费报销金额不能超过1000元")
                        elif expense_type.value == "餐费" and amount > 500:
                            errors.append("餐费报销金额不能超过500元")
                        elif expense_type.value == "其他" and amount > 200:
                            errors.append("其他费用报销金额不能超过200元")

                except (ValueError, TypeError):
                    pass

        elif form_type == FormType.LEAVE_REQUEST:
            # 请假单业务规则
            start_date = form_instance.field_values.get("start_date")
            end_date = form_instance.field_values.get("end_date")

            if start_date and end_date and start_date.value and end_date.value:
                try:
                    start_dt = datetime.strptime(str(start_date.value), "%Y-%m-%d")
                    end_dt = datetime.strptime(str(end_date.value), "%Y-%m-%d")

                    if end_dt <= start_dt:
                        errors.append("结束日期必须晚于开始日期")

                    # 计算请假天数
                    leave_days = (end_dt - start_dt).days + 1
                    leave_days_value = form_instance.field_values.get("leave_days")

                    if leave_days_value and leave_days_value.value:
                        try:
                            recorded_days = int(leave_days_value.value)
                            if recorded_days != leave_days:
                                errors.append(f"请假天数{recorded_days}与日期计算结果{leave_days}不一致")
                        except ValueError:
                            pass

                except ValueError:
                    pass

        return errors

    def get_form_instance(self, instance_id: str) -> Optional[FormInstance]:
        """获取表单实例"""
        return self.form_instances.get(instance_id)

    def save_form_instance(self, form_instance: FormInstance):
        """保存表单实例"""
        form_instance.updated_at = datetime.now()
        self.form_instances[form_instance.instance_id] = form_instance

    def delete_form_instance(self, instance_id: str):
        """删除表单实例"""
        if instance_id in self.form_instances:
            del self.form_instances[instance_id]

    def get_form_statistics(self) -> Dict[str, Any]:
        """获取表单统计信息"""
        stats = {
            "total_instances": len(self.form_instances),
            "status_distribution": {},
            "form_type_distribution": {}
        }

        for instance in self.form_instances.values():
            # 按状态统计
            status = instance.status
            stats["status_distribution"][status] = stats["status_distribution"].get(status, 0) + 1

            # 按表单类型统计
            form_type = instance.form_definition.form_type.value
            stats["form_type_distribution"][form_type] = stats["form_type_distribution"].get(form_type, 0) + 1

        return stats