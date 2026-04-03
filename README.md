# AI-OA 核心服务器

## 快速部署（阿里云）

### 1. 准备

- 阿里云ECS：2核4GB，Ubuntu 20.04
- 安全组开放：22, 80, 443端口
- 智谱AI API Key

### 2. 上传代码

```bash
# 本地打包
tar -czf oai-core.tar.gz *

# 上传到服务器
scp oai-core.tar.gz root@<ECS-IP>:/tmp/

# SSH登录
ssh root@<ECS-IP>
```

### 3. 自动部署

```bash
# 解压
cd /tmp
mkdir OAI-Core-Service
tar -xzf oai-core.tar.gz -C OAI-Core-Service/

# 运行部署脚本
cd OAI-Core-Service
bash deploy_to_aliyun.sh
```

### 4. 配置

```bash
# 编辑配置
vim /opt/ai-oa-core/.env

# 填写：
ZHIPU_API_KEY=你的智谱key
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
ALLOWED_API_KEYS=test_key_001
ADMIN_KEY=admin_key_123

# 重启
supervisorctl restart ai-oa-core
```

### 5. 验证

```bash
# 检查状态
supervisorctl status ai-oa-core

# 测试
curl http://localhost:9000/health
```

## 管理命令

```bash
# 查看状态
supervisorctl status ai-oa-core

# 重启
supervisorctl restart ai-oa-core

# 查看日志
tail -f /var/log/ai-oa-core/app.log
```

## API使用

```bash
# 健康检查
curl https://your-server/health

# 对话接口
curl -X POST https://your-server/ai/chat \
  -H "Authorization: Bearer test_key_001" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "你好"}]}'
```

完成！
