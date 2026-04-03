# AI-OA 核心服务器 - 阿里云部署指南

## 📋 目录

1. [准备工作](#准备工作)
2. [阿里云ECS配置](#阿里云ecs配置)
3. [部署步骤](#部署步骤)
4. [配置说明](#配置说明)
5. [验证测试](#验证测试)
6. [运维管理](#运维管理)
7. [故障排查](#故障排查)

---

## 准备工作

### 1. 所需资源

| 资源 | 推荐配置 | 说明 |
|------|---------|------|
| **ECS实例** | 2核4GB | 生产环境建议4核8GB |
| **操作系统** | Ubuntu 20.04 LTS | 或 CentOS 8+ |
| **磁盘** | 40GB SSD | 系统盘 |
| **带宽** | 5Mbps | 按需增加 |
| **地域** | 华北2（北京） | 就近选择 |

### 2. 成本估算

**基础配置（2核4GB）：**
- ECS费用：~200元/月
- 带宽费用：~50元/月
- 总计：**~250元/月**

**推荐配置（4核8GB）：**
- ECS费用：~400元/月
- 带宽费用：~100元/月
- 总计：**~500元/月**

### 3. 准备材料

- [ ] 阿里云账号（已实名认证）
- [ ] 智谱AI API Key
- [ ] 域名（可选，用于HTTPS）
- [ ] SSL证书（可选，可使用Let's Encrypt免费证书）

---

## 阿里云ECS配置

### 步骤1：购买ECS实例

1. 登录[阿里云控制台](https://ecs.console.aliyun.com/)

2. 点击"创建实例"

3. 选择配置：
   ```
   计费方式: 包年包月（推荐）或按量付费
   地域: 华北2（北京）或就近选择
   实例规格: ecs.c6.large（2核4GB）或更高
   镜像: Ubuntu 20.04 64位
   存储: 40GB ESSD云盘
   网络: 专有网络VPC
   公网带宽: 5Mbps
   ```

4. 安全组设置：
   - 勾选"HTTP(80)"
   - 勾选"HTTPS(443)"
   - 勾选"SSH(22)"

5. 设置实例密码（记住此密码，用于SSH登录）

6. 确认订单并支付

### 步骤2：配置安全组

1. 进入ECS控制台 → 实例 → 点击实例ID

2. 点击"安全组" → 点击安全组ID

3. 点击"配置规则" → "添加安全组规则"

4. 添加以下规则：

| 协议类型 | 端口范围 | 授权对象 | 描述 |
|---------|---------|---------|------|
| TCP | 80 | 0.0.0.0/0 | HTTP |
| TCP | 443 | 0.0.0.0/0 | HTTPS |
| TCP | 22 | 你的IP/32 | SSH（限制来源IP更安全） |

**可选：IP白名单**

如果只允许特定客户访问，可以设置：
```
TCP    443    1.2.3.4/32    客户A
TCP    443    5.6.7.8/32    客户B
```

### 步骤3：绑定弹性公网IP（如果需要）

1. 进入ECS控制台 → 实例

2. 点击"更多" → "网络和安全组" → "绑定弹性公网IP"

3. 选择已有EIP或购买新的

---

## 部署步骤

### 方法一：自动部署（推荐）

#### 1. 上传代码到服务器

在本地执行：

```bash
# 打包代码
cd /Users/reyvan/PycharmProjects/OAI-Core-Service
tar -czf oai-core-service.tar.gz *

# 上传到服务器
scp oai-core-service.tar.gz root@<ECS公网IP>:/tmp/

# SSH登录服务器
ssh root@<ECS公网IP>
```

#### 2. 解压代码

```bash
# 在服务器上执行
cd /tmp
mkdir -p OAI-Core-Service
tar -xzf oai-core-service.tar.gz -C OAI-Core-Service/
```

#### 3. 运行自动部署脚本

```bash
cd /tmp/OAI-Core-Service
bash deploy_to_aliyun.sh
```

脚本会自动完成：
- ✅ 安装系统依赖（Python, Nginx, Supervisor等）
- ✅ 创建应用用户和目录
- ✅ 安装Python依赖
- ✅ 配置Supervisor（进程管理）
- ✅ 配置Nginx（反向代理）
- ✅ 启动服务

#### 4. 配置环境变量

脚本运行完成后，编辑配置文件：

```bash
vim /opt/ai-oa-core/.env
```

填写以下关键配置：

```bash
# 智谱AI配置
ZHIPU_API_KEY=your_actual_api_key_here

# 加密密钥（用于提示词加密）
ENCRYPTION_KEY=your_fernet_encryption_key_here

# API Keys（分配给客户）
ALLOWED_API_KEYS=customer1_key,customer2_key,customer3_key

# 管理员Key
ADMIN_KEY=your_admin_key_here
```

**生成加密密钥：**

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

#### 5. 重启服务

```bash
supervisorctl restart ai-oa-core
```

---

### 方法二：手动部署

详细步骤见 [deploy_to_aliyun.sh](deploy_to_aliyun.sh) 脚本内容。

---

## 配置说明

### 1. 环境变量（.env）

位置：`/opt/ai-oa-core/.env`

```bash
# 基础配置
ENVIRONMENT=production          # 运行环境
HOST=0.0.0.0                   # 监听地址
PORT=9000                      # 监听端口
DEBUG=false                    # 调试模式（生产环境必须false）
ENABLE_DOCS=false              # API文档（生产环境建议关闭）

# 智谱AI配置
ZHIPU_API_KEY=your_key_here    # 智谱AI API Key

# 安全配置
ENCRYPTION_KEY=your_key_here   # 用于提示词加密
ALLOWED_API_KEYS=key1,key2     # 客户API Keys（逗号分隔）
ADMIN_KEY=your_admin_key       # 管理员Key

# 数据库（可选，用于客户管理）
DATABASE_URL=postgresql://...

# 日志
LOG_LEVEL=INFO
LOG_DIR=logs
```

### 2. Nginx配置

位置：`/etc/nginx/sites-available/ai-oa-core`

关键配置：

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;  # 修改为实际域名

    # SSL证书
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # IP白名单（可选）
    allow 1.2.3.4;  # 客户1
    allow 5.6.7.8;  # 客户2
    deny all;

    location / {
        proxy_pass http://127.0.0.1:9000;
        # ...
    }
}
```

**配置SSL证书（Let's Encrypt）：**

```bash
# 安装certbot
apt-get install -y certbot python3-certbot-nginx

# 获取证书
certbot --nginx -d your-domain.com

# 自动续期（添加到crontab）
0 0 1 * * certbot renew --quiet
```

### 3. Supervisor配置

位置：`/etc/supervisor/conf.d/ai-oa-core.conf`

```ini
[program:ai-oa-core]
directory=/opt/ai-oa-core
command=/opt/ai-oa-core/venv/bin/python core_server.py
user=ai-oa
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/ai-oa-core/app.log
```

---

## 验证测试

### 1. 检查服务状态

```bash
# 检查应用进程
supervisorctl status ai-oa-core

# 应该显示: RUNNING

# 检查端口监听
netstat -tlnp | grep -E ':(80|443|9000)'

# 应该看到80, 443, 9000端口在监听
```

### 2. 测试健康检查

```bash
# 本地测试
curl http://localhost:9000/health

# 应该返回:
# {
#   "status": "healthy",
#   "timestamp": "...",
#   "service": "ai-oa-core",
#   "version": "1.0.0"
# }
```

### 3. 测试API接口

```bash
# 准备测试请求
export TEST_API_KEY="your_test_api_key"

# 测试对话接口
curl -X POST https://your-server-ip/ai/chat \
  -H "Authorization: Bearer $TEST_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'

# 应该返回成功响应
```

### 4. 查看日志

```bash
# 应用日志
tail -f /var/log/ai-oa-core/app.log

# Nginx访问日志
tail -f /var/log/ai-oa-core/nginx_access.log

# Nginx错误日志
tail -f /var/log/ai-oa-core/nginx_error.log
```

---

## 运维管理

### 常用命令

```bash
# 查看服务状态
supervisorctl status ai-oa-core

# 启动服务
supervisorctl start ai-oa-core

# 停止服务
supervisorctl stop ai-oa-core

# 重启服务
supervisorctl restart ai-oa-core

# 查看日志
tail -f /var/log/ai-oa-core/app.log

# 重启Nginx
systemctl restart nginx

# 检查Nginx配置
nginx -t
```

### 更新代码

```bash
# 1. 备份当前代码
cd /opt/ai-oa-core
tar -czf backup-$(date +%Y%m%d-%H%M%S).tar.gz .

# 2. 上传新代码
scp new-code.tar.gz root@<ECS-IP>:/tmp/

# 3. 解压覆盖
cd /opt/ai-oa-core
tar -xzf /tmp/new-code.tar.gz

# 4. 重启服务
supervisorctl restart ai-oa-core
```

### 日志轮转

```bash
# 配置日志轮转
cat > /etc/logrotate.d/ai-oa-core <<EOF
/var/log/ai-oa-core/*.log {
    daily
    rotate 30
    missingok
    notifempty
    compress
    delaycompress
    sharedscripts
    postrotate
        supervisorctl restart ai-oa-core > /dev/null
    endscript
}
EOF
```

### 监控告警

#### 1. 系统资源监控

```bash
# 安装htop
apt-get install -y htop

# 查看资源使用
htop
```

#### 2. 服务可用性监控

创建监控脚本：

```bash
cat > /opt/ai-oa-core/health_check.sh <<'EOF'
#!/bin/bash

HEALTH_URL="http://localhost:9000/health"
ALERT_EMAIL="your-email@example.com"

response=$(curl -s -o /dev/null -w "%{http_code}" $HEALTH_URL)

if [ "$response" != "200" ]; then
    echo "❌ 服务健康检查失败: HTTP $response" | \
        mail -s "AI-OA核心服务告警" $ALERT_EMAIL
fi
EOF

chmod +x /opt/ai-oa-core/health_check.sh

# 添加到crontab（每5分钟检查一次）
crontab -e
# 添加：
*/5 * * * * /opt/ai-oa-core/health_check.sh
```

#### 3. 磁盘空间监控

```bash
# 检查磁盘使用
df -h

# 如果日志占用过多，清理旧日志
find /var/log/ai-oa-core -name "*.log.*" -mtime +30 -delete
```

---

## 故障排查

### 问题1：服务无法启动

**症状：** `supervisorctl status` 显示 `FATAL`

**排查步骤：**

```bash
# 1. 查看错误日志
tail -100 /var/log/ai-oa-core/app.log

# 2. 检查配置文件
cat /opt/ai-oa-core/.env

# 3. 检查Python环境
/opt/ai-oa-core/venv/bin/python --version

# 4. 手动启动（查看详细错误）
cd /opt/ai-oa-core
sudo -u ai-oa /opt/ai-oa-core/venv/bin/python core_server.py
```

**常见原因：**
- `.env` 配置错误（缺少必需的环境变量）
- Python依赖未安装
- 端口被占用

### 问题2：API调用返回401

**症状：** `Invalid API key`

**排查步骤：**

```bash
# 1. 检查API Key配置
grep ALLOWED_API_KEYS /opt/ai-oa-core/.env

# 2. 检查请求头
# 确保使用: Authorization: Bearer <api_key>

# 3. 查看应用日志
tail -f /var/log/ai-oa-core/app.log | grep "API Key"
```

### 问题3：智谱AI调用失败

**症状：** LLM调用返回错误

**排查步骤：**

```bash
# 1. 检查API Key
grep ZHIPU_API_KEY /opt/ai-oa-core/.env

# 2. 测试API Key
curl -X POST https://open.bigmodel.cn/api/paas/v4/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4",
    "messages": [{"role": "user", "content": "hello"}]
  }'

# 3. 检查网络
ping open.bigmodel.cn
```

### 问题4：Nginx返回502

**症状：** 浏览器访问返回 `502 Bad Gateway`

**排查步骤：**

```bash
# 1. 检查后端服务是否运行
supervisorctl status ai-oa-core

# 2. 检查端口监听
netstat -tlnp | grep 9000

# 3. 测试后端
curl http://localhost:9000/health

# 4. 检查Nginx错误日志
tail -f /var/log/nginx/error.log
```

### 问题5：内存不足

**症状：** 服务频繁重启，日志显示内存错误

**解决方案：**

```bash
# 1. 升级ECS实例规格
# 阿里云控制台 → 实例 → 升降配

# 2. 或者优化配置，减少worker数
vim /opt/ai-oa-core/.env
# 修改: WORKERS=2
```

---

## 安全建议

### 1. 定期更新系统

```bash
# Ubuntu
apt-get update && apt-get upgrade -y

# CentOS
yum update -y
```

### 2. 配置防火墙

```bash
# 只允许必要的端口
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

### 3. 修改SSH端口（可选）

```bash
# 编辑SSH配置
vim /etc/ssh/sshd_config

# 修改端口
Port 2222

# 重启SSH
systemctl restart sshd

# 更新安全组（开放2222端口）
```

### 4. 定期备份

```bash
# 创建备份脚本
cat > /opt/backup.sh <<'EOF'
#!/bin/bash
BACKUP_DIR="/data/backup"
DATE=$(date +%Y%m%d-%H%M%S)

mkdir -p $BACKUP_DIR

# 备份代码
tar -czf $BACKUP_DIR/code-$DATE.tar.gz /opt/ai-oa-core

# 备份配置
cp /opt/ai-oa-core/.env $BACKUP_DIR/env-$DATE

# 删除30天前的备份
find $BACKUP_DIR -name "*.tar.gz" -mtime +30 -delete

echo "备份完成: $DATE"
EOF

chmod +x /opt/backup.sh

# 添加到crontab（每天凌晨2点备份）
0 2 * * * /opt/backup.sh
```

---

## 联系支持

如果遇到问题，请查看日志或联系技术支持：

- 📧 Email: your-email@example.com
- 📝 日志位置: `/var/log/ai-oa-core/`
- 📚 文档: 本文档

---

**最后更新**: 2025-12-02
