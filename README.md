# FontHub

[![GitHub](https://img.shields.io/badge/GitHub-kesardev%2Ffont--hub-181717?logo=github)](https://github.com/kesardev/font-hub)
[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-kesardev%2Ffont--hub-2496ED?logo=docker)](https://hub.docker.com/r/kesardev/font-hub)

自托管的字体库管理工具：扫描指定目录下的字体文件，集中查看元数据与特征、检测重复、在线预览缺字，并通过回收站安全删除。适合管理媒体服务器字体目录、设计素材库，或任意规模的字体归档。

## 功能

- 递归扫描 `ttf` / `otf` / `ttc` / `woff` / `woff2`，保留原始目录结构
- 列表展示文件名、字体名称、格式、大小、版本、面数、解析状态，支持搜索、排序与文件夹筛选
- 详情页展示完整名称、PostScript 名、字形数、Units/Em，以及 TTC 的每个字体面
- 按需计算 MD5 / SHA1 / SHA256，支持后台批量哈希、进度显示与中断
- 重复文件分组并相邻高亮，可只看重复文件，统计可回收空间
- 上传支持多文件、文件夹（保留相对路径）；内容相同的文件自动跳过并提示原路径
- 同名冲突可选重命名（自动给出 `name (1).ext`）或跳过，支持对全部冲突套用同一选择
- 预览分中文（简/繁）、英文（大/小写）、标点（中/英/数字）、特殊四组，逐字高亮缺字
- 无中文字形的字体自动隐藏中文预览；只有简体或只有繁体的字体自动折叠为单行
- 大小写识别与字形轮廓比对，覆盖 upper-only / lower-only / unicase 等情况
- 回收站支持恢复与永久删除，保留期 1–3650 天或永久，到期自动清理
- 批量选择、批量移入回收站、批量永久删除，以及下载原始字体文件
- 设置保存在 `config/settings.json`，预览文本可自定义并一键恢复默认

## 快速开始

~~~bash
docker compose -f compose.prod.yaml up -d
~~~

启动后访问 http://<host>:13578。默认监听 13578，可在 compose 文件里改成其他端口。

也可以用 docker run 直接启动，关键是把字体目录、配置、状态和回收站四个目录挂进容器，并设置对应环境变量。

## 示例 compose 文件

可直接复制使用，按需修改宿主机路径与端口：

~~~yaml
services:
  font-hub:
    image: kesardev/font-hub:latest
    container_name: font-hub
    user: '1000:0'
    ports:
      - '13578:8080'
    volumes:
      - /srv/fonts:/data/fonts
      - /srv/font-hub/recycle:/data/recycle
      - /srv/font-hub/config:/data/config
      - /srv/font-hub/state:/data/state
    environment:
      - TZ=Asia/Shanghai
      - FONT_ROOT=/data/fonts
      - STATE_DIR=/data/state
      - CONFIG_DIR=/data/config
      - RECYCLE_DIR=/data/recycle
      - HOME=/data/state
      - AUTO_SCAN=1
    restart: unless-stopped
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
~~~

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| FONT_ROOT | /data/fonts | 字体根目录，映射宿主机字体目录 |
| STATE_DIR | /data/state | SQLite 数据库与预览缓存 |
| CONFIG_DIR | /data/config | 设置文件目录，存放 settings.json |
| RECYCLE_DIR | /data/recycle | 回收站目录，建议与字体目录同一文件系统 |
| SCAN_EXTENSIONS | .ttf,.otf,.ttc,.woff,.woff2 | 自定义扫描扩展名，逗号分隔 |
| AUTO_SCAN | 1 | 启动时自动扫描 |
| TZ | - | 时区，例如 Asia/Shanghai |

设置项（回收站天数、四类预览文本）在页面「设置」中修改，写入 config/settings.json，升级镜像不会丢失。

## 数据与权限

- 扫描只读；上传、回收、恢复与永久删除需要字体目录写权限
- 不改动已有文件的名称、目录结构和权限，删除操作只是移动到回收站
- 容器默认以 1000:0 运行，请确保该用户对字体目录有读写权限
- 无内置鉴权，建议部署在可信内网，或置于带认证的反向代理之后

## 本地开发

~~~bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
~~~

测试脚本位于 tests/，包含接口冒烟测试与前端 UI 测试。

## 目录结构

~~~
app/
  main.py          API 与路由
  fonts.py         扫描与元数据解析
  preview.py       预览字体与缺字检测
  recycle.py       回收站
  settings_store.py / project_settings.py / preview_settings.py
  static/          前端页面（无构建步骤）
tests/             冒烟与 UI 测试
compose.yaml       本地构建
compose.prod.yaml  生产部署
~~~

## 说明

- woff / woff2 可以管理、预览与下载，但部分字幕渲染器只识别 ttf / otf / ttc
- 单次批量删除上限 500 个，更大规模建议分批操作
- 首次预览 TTC 需要抽取字体面，19 MB 左右的文件约 30 秒，之后走缓存
