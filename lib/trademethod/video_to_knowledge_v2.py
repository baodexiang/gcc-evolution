"""
视频批量转知识库工具 v2
Whisper 本地转录 + DeepSeek 智能总结
修复：中文路径问题

使用方法：
1. pip install openai-whisper openai ffmpeg-python
2. 设置环境变量 DEEPSEEK_API_KEY
3. 把这个脚本放到视频文件夹的父目录
4. 运行 python video_to_knowledge.py
"""

import os
import sys
import whisper
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from openai import OpenAI

# 修复 Windows 中文编码
if sys.platform == 'win32':
    import locale
    locale.setlocale(locale.LC_ALL, '')

# ============ 配置 ============

MODEL_SIZE = "medium"
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v'}
OUTPUT_DIR = "txt_output"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
ENABLE_SUMMARY = True

# ============ 配置结束 ============


def get_script_dir():
    return Path(__file__).parent.resolve()


def find_all_videos(root_dir):
    videos = []
    root_path = Path(root_dir)
    
    for item in root_path.iterdir():
        if item.name == OUTPUT_DIR:
            continue
            
        if item.is_dir():
            for video_file in item.rglob('*'):
                if video_file.suffix.lower() in VIDEO_EXTENSIONS:
                    videos.append(video_file)
        elif item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
            videos.append(item)
    
    return sorted(videos)


def transcribe_video(model, video_path):
    """Whisper 转录视频 - 处理中文路径"""
    print(f"  [Whisper] 正在转录...")
    
    # 检查路径是否包含非 ASCII 字符
    video_str = str(video_path)
    use_temp = False
    temp_path = None
    
    try:
        video_str.encode('ascii')
    except UnicodeEncodeError:
        # 包含中文，需要复制到临时目录
        use_temp = True
        temp_dir = tempfile.gettempdir()
        # 使用简单的临时文件名
        temp_filename = f"temp_video_{datetime.now().strftime('%H%M%S')}{video_path.suffix}"
        temp_path = os.path.join(temp_dir, temp_filename)
        print(f"  [Whisper] 复制到临时文件...")
        shutil.copy2(video_path, temp_path)
        video_str = temp_path
    
    try:
        result = model.transcribe(
            video_str,
            language="zh",
            verbose=False
        )
        
        # 带时间戳的文本
        lines = []
        for segment in result.get("segments", []):
            start = segment["start"]
            text = segment["text"].strip()
            start_str = f"{int(start//60):02d}:{int(start%60):02d}"
            lines.append(f"[{start_str}] {text}")
        
        timestamped_text = "\n".join(lines)
        plain_text = result["text"]
        
        return timestamped_text, plain_text
        
    finally:
        # 清理临时文件
        if use_temp and temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass


def summarize_with_deepseek(client, text, video_name):
    """用 DeepSeek 总结提炼"""
    print(f"  [DeepSeek] 正在总结...")
    
    max_chars = 50000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[文本过长，已截取前半部分]"
    
    prompt = f"""你是一个专业的交易知识整理专家。请分析以下视频转录内容，提取核心知识点。

视频标题：{video_name}

转录内容：
{text}

请按以下格式输出：

## 📌 核心主题
[一句话概括这个视频讲什么]

## 🎯 关键知识点
[列出 5-10 个最重要的知识点，每个用 1-2 句话说清楚]

## 📊 实战要点
[提取可以直接用于交易的具体方法、指标、规则]

## 💡 重要概念
[解释视频中提到的专业术语和概念]

## 🔗 知识关联
[这个内容和其他交易理论（如维科夫、K线、量价）的关系]

请用简洁专业的中文输出，重点突出可操作的交易知识。
"""

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是专业的交易知识整理专家，擅长从视频内容中提取核心交易知识。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=4000
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"  [DeepSeek] 总结失败: {e}")
        return None


def create_knowledge_card(video_name, summary):
    """生成知识卡片"""
    card = f"""# {video_name}

> 📅 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}
> 🎬 来源：视频课程转录 + AI 总结

---

{summary}

---

*本文档由 AI 自动生成，用于知识库检索*
"""
    return card


def process_video(model, client, video_path, output_dir, script_dir):
    """处理单个视频"""
    rel_path = video_path.relative_to(script_dir)
    video_name = video_path.stem
    
    output_subdir = output_dir / rel_path.parent
    output_subdir.mkdir(parents=True, exist_ok=True)
    
    raw_path = output_subdir / f"{video_name}_原始转录.txt"
    summary_path = output_subdir / f"{video_name}_精华总结.txt"
    card_path = output_subdir / f"{video_name}_知识卡片.md"
    
    if card_path.exists():
        print(f"  ⏭️ 跳过（已存在）")
        return True
    
    try:
        # 1. Whisper 转录
        if raw_path.exists():
            print(f"  [Whisper] 读取已有转录...")
            with open(raw_path, "r", encoding="utf-8") as f:
                content = f.read()
            # 跳过头部信息
            if "\n\n" in content:
                timestamped_text = content.split("\n\n", 1)[1]
            else:
                timestamped_text = content
            plain_text = timestamped_text
        else:
            timestamped_text, plain_text = transcribe_video(model, video_path)
            
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(f"# {video_name}\n")
                f.write(f"# 转录时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# 源文件: {video_path}\n\n")
                f.write(timestamped_text)
            print(f"  ✅ 原始转录已保存")
        
        # 2. DeepSeek 总结
        if ENABLE_SUMMARY and client:
            summary = summarize_with_deepseek(client, plain_text, video_name)
            
            if summary:
                with open(summary_path, "w", encoding="utf-8") as f:
                    f.write(summary)
                print(f"  ✅ 精华总结已保存")
                
                card = create_knowledge_card(video_name, summary)
                with open(card_path, "w", encoding="utf-8") as f:
                    f.write(card)
                print(f"  ✅ 知识卡片已保存")
        else:
            # 没有 DeepSeek 时，直接生成简单卡片
            card = f"""# {video_name}

> 📅 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

---

{plain_text[:5000]}

---
"""
            with open(card_path, "w", encoding="utf-8") as f:
                f.write(card)
            print(f"  ✅ 知识卡片已保存（无总结）")
        
        return True
        
    except Exception as e:
        print(f"  ❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    script_dir = get_script_dir()
    output_dir = script_dir / OUTPUT_DIR
    
    print("=" * 60)
    print("🎬 视频批量转知识库工具 v2")
    print("=" * 60)
    print(f"脚本目录: {script_dir}")
    print(f"输出目录: {output_dir}")
    print(f"Whisper 模型: {MODEL_SIZE}")
    print(f"DeepSeek 总结: {'启用' if ENABLE_SUMMARY else '禁用'}")
    print()
    
    # 检查 ffmpeg
    if shutil.which("ffmpeg") is None:
        print("⚠️ 警告: 未检测到 ffmpeg，可能无法处理某些视频格式")
        print("   请安装 ffmpeg: https://ffmpeg.org/download.html")
        print()
    
    # 检查 DeepSeek API
    client = None
    if ENABLE_SUMMARY:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if api_key:
            client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
            print("✅ DeepSeek API 已连接")
        else:
            print("⚠️ 未找到 DEEPSEEK_API_KEY，将只进行转录")
    
    # 查找视频
    print("\n正在扫描视频文件...")
    videos = find_all_videos(script_dir)
    
    if not videos:
        print("❌ 没有找到视频文件!")
        return
    
    print(f"找到 {len(videos)} 个视频文件:")
    for i, v in enumerate(videos[:10], 1):
        rel_path = v.relative_to(script_dir)
        print(f"  {i}. {rel_path}")
    if len(videos) > 10:
        print(f"  ... 还有 {len(videos) - 10} 个")
    
    print()
    input("按 Enter 开始处理...")
    
    # 加载 Whisper
    print(f"\n正在加载 Whisper {MODEL_SIZE} 模型...")
    model = whisper.load_model(MODEL_SIZE)
    print("✅ 模型加载完成!")
    
    # 处理视频
    success = 0
    failed = 0
    
    for i, video_path in enumerate(videos, 1):
        print(f"\n[{i}/{len(videos)}] {video_path.name}")
        
        if process_video(model, client, video_path, output_dir, script_dir):
            success += 1
        else:
            failed += 1
    
    # 总结
    print("\n" + "=" * 60)
    print("🎉 处理完成!")
    print("=" * 60)
    print(f"成功: {success}")
    print(f"失败: {failed}")
    print(f"\n输出目录: {output_dir}")
    print(f"\n📌 下一步: 把 *_知识卡片.md 文件上传到 NotebookLM")


if __name__ == "__main__":
    main()
