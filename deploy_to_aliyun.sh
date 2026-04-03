#!/bin/bash

# ============================================================
# AI-OA 核心服务器 - 阿里云部署脚本
# ============================================================
#
# 使用方法:
#   1. 在阿里云ECS上创建新实例
#   2. 上传此脚本和代码到服务器
#   3. 执行: bash deploy_to_aliyun.sh
#
# 前置要求:
#   - Ubuntu 20.04+ / CentOS 8+
#   - Python 3.11+
#   - root或sudo权限
# ============================================================

set -e  # 遇到错误立即退出

echo "============================================"
echo "  AI-OA 核心服务器 - 阿里云部署"
echo "============================================"
echo ""

# ==================== 配置变量 ====================
APP_NAME="ai-oa-core"
APP_USER="ai-oa"
APP_DIR="/opt/${APP_NAME}"
LOG_DIR="/var/log/${APP_NAME}"
PYTHON_VERSION="3.12"

# ==================== 检查权限 ====================
if [ "$EUID" -ne 0 ]; then
    echo "❌ 请使用root权限运行此脚本"
    echo "   sudo bash $0"
    exit 1
fi

echo "✅ 权限检查通过"

# ==================== 1. 安装系统依赖 ====================
echo ""
echo "📦 步骤1: 安装系统依赖..."

# 检测操作系统
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "❌ 无法检测操作系统"
    exit 1
fi

case $OS in
    ubuntu|debian)
        apt-get update
        apt-get install -y \
            python${PYTHON_VERSION} \
            python${PYTHON_VERSION}-venv \
            python3-pip \
            nginx \
            supervisor \
            git \
            curl \
            vim
        ;;
    centos|rhel)
        yum install -y epel-release
        yum install -y \
            python${PYTHON_VERSION} \
            python${PYTHON_VERSION}-pip \
            nginx \
            supervisor \
            git \
            curl \
            vim
        ;;
    *)
        echo "❌ 不支持的操作系统: $OS"
        exit 1
        ;;
esac

echo "✅ 系统依赖安装完成"

# ==================== 2. 创建应用用户 ====================
echo ""
echo "👤 步骤2: 创建应用用户..."

if id "$APP_USER" &>/dev/null; then
    echo "⚠️  用户 $APP_USER 已存在，跳过创建"
else
    useradd -r -m -s /bin/bash $APP_USER
    echo "✅ 用户 $APP_USER 创建成功"
fi

# ==================== 3. 创建目录结构 ====================
echo ""
echo "📁 步骤3: 创建目录结构..."

mkdir -p $APP_DIR
mkdir -p $LOG_DIR
mkdir -p /etc/${APP_NAME}

chown -R $APP_USER:$APP_USER $APP_DIR
chown -R $APP_USER:$APP_USER $LOG_DIR

echo "✅ 目录结构创建完成"

# ==================== 4. 部署应用代码 ====================
echo ""
echo "📦 步骤4: 部署应用代码..."

# 假设代码已经上传到/opt/OAI-Core-Service
if [ -d "/opt/OAI-Core-Service" ]; then
    cp -r /opt/OAI-Core-Service/* $APP_DIR/
    echo "✅ 代码复制完成"
else
    echo "⚠️  代码目录不存在，请确保已上传代码到 /opt/OAI-Core-Service"
    echo "   可以使用: scp -r OAI-Core-Service root@<server-ip>:/tmp/"
    exit 1
fi

chown -R $APP_USER:$APP_USER $APP_DIR

# ==================== 5. 创建Python虚拟环境 ====================
echo ""
echo "🐍 步骤5: 创建Python虚拟环境..."

cd $APP_DIR

sudo -u $APP_USER python${PYTHON_VERSION} -m venv venv

echo "✅ 虚拟环境创建完成"

# ==================== 6. 安装Python依赖 ====================
echo ""
echo "📚 步骤6: 安装Python依赖..."

sudo -u $APP_USER $APP_DIR/venv/bin/pip install --upgrade pip
sudo -u $APP_USER $APP_DIR/venv/bin/pip install -r $APP_DIR/requirements.txt

echo "✅ Python依赖安装完成"

# ==================== 7. 配置环境变量 ====================
echo ""
echo "⚙️  步骤7: 配置环境变量..."

if [ -f "$APP_DIR/.env" ]; then
    echo "⚠️  .env文件已存在，跳过创建"
else
    echo "📝 请配置.env文件..."
    echo "   编辑: vim $APP_DIR/.env"
    echo "   参考: $APP_DIR/.env.example"

    # 创建默认配置
    cat > $APP_DIR/.env <<EOF
ENVIRONMENT=production
HOST=0.0.0.0
PORT=9000
ZHIPU_API_KEY=
ENCRYPTION_KEY=
ALLOWED_API_KEYS=
ADMIN_KEY=
EOF

    chown $APP_USER:$APP_USER $APP_DIR/.env
    chmod 600 $APP_DIR/.env  # 只有owner可读写

    echo ""
    echo "⚠️  重要：请立即编辑.env文件填写配置！"
    echo "   vim $APP_DIR/.env"
    echo ""
    read -p "按Enter键继续..."
fi

# ==================== 8. 配置Supervisor ====================
echo ""
echo "🔧 步骤8: 配置Supervisor..."

cat > /etc/supervisor/conf.d/${APP_NAME}.conf <<EOF
[program:${APP_NAME}]
directory=$APP_DIR
command=$APP_DIR/venv/bin/python core_server.py
user=$APP_USER
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$LOG_DIR/app.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
environment=PATH="$APP_DIR/venv/bin"
stopwaitsecs=30
stopsignal=TERM
EOF

echo "✅ Supervisor配置完成"

# ==================== 9. 配置Nginx ====================
echo ""
echo "🌐 步骤9: 配置Nginx..."

cat > /etc/nginx/sites-available/${APP_NAME} <<EOF
# AI-OA 核心服务器 Nginx配置

upstream core_backend {
    server 127.0.0.1:9000;
}

server {
    listen 80;
    server_name _;

    # 重定向到HTTPS
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;  # 修改为实际域名

    # SSL证书配置（使用Let's Encrypt）
    # ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # 临时自签名证书（仅用于测试）
    ssl_certificate /etc/nginx/ssl/self-signed.crt;
    ssl_certificate_key /etc/nginx/ssl/self-signed.key;

    # SSL安全配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # IP白名单（可选，限制只有授权客户可访问）
    # allow 1.2.3.4;  # 客户1 IP
    # allow 5.6.7.8;  # 客户2 IP
    # deny all;

    # 日志
    access_log $LOG_DIR/nginx_access.log;
    error_log $LOG_DIR/nginx_error.log;

    # 代理到后端
    location / {
        proxy_pass http://core_backend;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # 超时配置
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;

        # 缓冲配置
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }

    # 健康检查端点（无需认证）
    location /health {
        proxy_pass http://core_backend;
        access_log off;
    }
}
EOF

# 创建软链接
if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
    ln -sf /etc/nginx/sites-available/${APP_NAME} /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default  # 删除默认配置
fi

# 创建自签名证书（临时，生产环境应使用Let's Encrypt）
mkdir -p /etc/nginx/ssl
if [ ! -f /etc/nginx/ssl/self-signed.crt ]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/self-signed.key \
        -out /etc/nginx/ssl/self-signed.crt \
        -subj "/C=CN/ST=Beijing/L=Beijing/O=AI-OA/CN=localhost"
fi

# 测试Nginx配置
nginx -t

echo "✅ Nginx配置完成"

# ==================== 10. 配置防火墙 ====================
echo ""
echo "🔥 步骤10: 配置防火墙..."

# 检查是否有防火墙
if command -v ufw &> /dev/null; then
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 22/tcp  # SSH
    # ufw enable  # 谨慎：可能断开SSH
    echo "✅ UFW防火墙规则已配置（未启用）"
elif command -v firewall-cmd &> /dev/null; then
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --permanent --add-service=ssh
    firewall-cmd --reload
    echo "✅ firewalld防火墙规则已配置"
else
    echo "⚠️  未检测到防火墙，建议手动配置阿里云安全组"
fi

# ==================== 11. 启动服务 ====================
echo ""
echo "🚀 步骤11: 启动服务..."

# 重启Supervisor
systemctl restart supervisor
systemctl enable supervisor

# 启动应用
supervisorctl reread
supervisorctl update
supervisorctl start ${APP_NAME}

# 启动Nginx
systemctl restart nginx
systemctl enable nginx

echo "✅ 服务启动完成"

# ==================== 12. 验证部署 ====================
echo ""
echo "🔍 步骤12: 验证部署..."

sleep 3

# 检查应用状态
echo ""
echo "应用状态:"
supervisorctl status ${APP_NAME}

# 检查端口
echo ""
echo "端口监听:"
netstat -tlnp | grep -E ':(80|443|9000)'

# 测试健康检查
echo ""
echo "健康检查:"
curl -s http://localhost:9000/health | python3 -m json.tool || echo "❌ 健康检查失败"

# ==================== 完成 ====================
echo ""
echo "============================================"
echo "  🎉 部署完成！"
echo "============================================"
echo ""
echo "📋 服务信息:"
echo "   应用目录: $APP_DIR"
echo "   日志目录: $LOG_DIR"
echo "   配置文件: $APP_DIR/.env"
echo ""
echo "🔧 管理命令:"
echo "   查看状态:   supervisorctl status ${APP_NAME}"
echo "   启动服务:   supervisorctl start ${APP_NAME}"
echo "   停止服务:   supervisorctl stop ${APP_NAME}"
echo "   重启服务:   supervisorctl restart ${APP_NAME}"
echo "   查看日志:   tail -f $LOG_DIR/app.log"
echo "   Nginx日志:  tail -f $LOG_DIR/nginx_access.log"
echo ""
echo "⚠️  重要提醒:"
echo "   1. 修改.env文件填写真实配置: vim $APP_DIR/.env"
echo "   2. 配置SSL证书（Let's Encrypt）"
echo "   3. 配置Nginx域名: vim /etc/nginx/sites-available/${APP_NAME}"
echo "   4. 配置阿里云安全组（开放80, 443端口）"
echo "   5. 可选：配置IP白名单限制访问"
echo ""
echo "🔗 访问地址:"
echo "   HTTP:  http://$(hostname -I | awk '{print $1}')"
echo "   HTTPS: https://$(hostname -I | awk '{print $1}')"
echo ""
echo "完成后请重启服务: supervisorctl restart ${APP_NAME}"
echo ""
