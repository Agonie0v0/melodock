"""Local audio diagnostics and derived files. Inputs are never replaced."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

FORMATS = {'flac': ['-c:a', 'flac'], 'mp3': ['-c:a', 'libmp3lame'],
           'm4a': ['-c:a', 'aac'], 'opus': ['-c:a', 'libopus'], 'wav': ['-c:a', 'pcm_s16le']}


def executable(name):
    configured = os.getenv('MUSICDL_' + name.upper())
    value = shutil.which(configured or name)
    if configured and not value:
        raise ValueError(f'配置的 {name} 路径不可用，请检查 MUSICDL_{name.upper()}')
    if not value and name == 'ffmpeg':
        try:
            import imageio_ffmpeg
            value = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    if not value:
        raise ValueError(f'未找到 {name}，请安装后配置 MUSICDL_{name.upper()}')
    return value


def available(name):
    try:
        executable(name)
        return True
    except (ValueError, OSError):
        return False


def run(args, cancelled=lambda: False, timeout=1800):
    import time
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    started = time.monotonic()
    try:
        while True:
            if cancelled():
                raise ValueError('处理已取消，原文件已保留')
            if time.monotonic() - started > timeout:
                raise ValueError('音频处理超时，原文件已保留')
            try:
                stdout, stderr = process.communicate(timeout=.3)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            detail = stderr.decode('utf-8', errors='replace')
            raise ValueError('音频处理失败：' + (detail[:500] if len(detail) > 800 else detail))
        return stdout
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def audio_hash(path, cancelled=lambda: False):
    result = run([executable('ffmpeg'), '-v', 'error', '-xerror', '-i', str(path), '-map', '0:a:0',
                  '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s32le', '-f', 'hash', '-hash', 'sha256', '-'], cancelled)
    return result.decode().strip()


def inspect_audio(path, metadata, cancelled=lambda: False):
    run([executable('ffmpeg'), '-v', 'error', '-xerror', '-i', str(path), '-map', '0:a:0', '-f', 'null', '-'], cancelled)
    return {key: metadata.get(key) for key in ('duration', 'bitrate', 'sample_rate', 'channels', 'bits_per_sample')}


def convert(source, target, options, *, start=None, end=None, cancelled=lambda: False):
    command = [executable('ffmpeg'), '-v', 'error', '-xerror', '-nostdin', '-n', '-i', str(source)]
    if start is not None:
        command += ['-ss', str(start)]
    if end is not None:
        command += ['-t', str(end - (start or 0))]
    fmt = options.get('output_format', 'flac')
    command += ['-map', '0:a:0', '-vn', '-map_metadata', '-1', *FORMATS[fmt]]
    if fmt in {'mp3', 'm4a', 'opus'}:
        command += ['-b:a', str(options.get('bitrate') or (128 if fmt == 'opus' else 320)) + 'k']
    if options.get('sample_rate'):
        command += ['-ar', str(options['sample_rate'])]
    run([*command, str(target)], cancelled)


def cue_tracks(path, text, duration):
    """Parse INDEX 01 boundaries. Each selected audio consumes its own FILE block."""
    tracks, current, current_file, album, performer = [], None, None, '', ''
    for line in text.splitlines():
        line = line.strip()
        match = re.fullmatch(r'FILE\s+"([^"]+)"\s+\S+', line, re.I)
        if match:
            current_file, current = match[1], None
            continue
        match = re.fullmatch(r'TRACK\s+(\d+)\s+AUDIO', line, re.I)
        if match:
            current = {'track_number': str(int(match[1])), 'title': '', 'artist': performer, 'file': current_file}
            tracks.append(current)
            continue
        match = re.fullmatch(r'(TITLE|PERFORMER)\s+"?(.*?)"?', line, re.I)
        if match:
            if current is None:
                if match[1].upper() == 'TITLE': album = match[2]
                else: performer = match[2]
            else:
                current['title' if match[1].upper() == 'TITLE' else 'artist'] = match[2]
            continue
        match = re.fullmatch(r'INDEX\s+01\s+(\d+):(\d{2}):(\d{2})', line, re.I)
        if match and current:
            minutes, seconds, frames = map(int, match.groups())
            if seconds >= 60 or frames >= 75:
                raise ValueError('CUE 时间格式无效')
            current['start'] = minutes * 60 + seconds + frames / 75
    selected = [t for t in tracks if t['file'] and Path(t['file'].replace('\\', '/')).name.casefold() == path.name.casefold()]
    if len(selected) > 1000:
        raise ValueError('每次最多分割 1000 条音轨')
    if not selected or any('start' not in t for t in selected):
        raise ValueError('CUE 没有匹配当前音频的 FILE / INDEX 01')
    for i, track in enumerate(selected):
        end = selected[i + 1]['start'] if i + 1 < len(selected) else duration
        if not duration or not 0 <= track['start'] < end <= duration + .1:
            raise ValueError('CUE 分轨时间超出音频或不是递增顺序')
        track.update(end=end, album=album, album_artist=performer,
                     title=track['title'] or 'Track ' + track['track_number'])
    return selected


def fingerprint(path):
    data = json.loads(run([executable('fpcalc'), '-json', '-length', '120', str(path)], timeout=120))
    if not data.get('fingerprint') or not data.get('duration'):
        raise ValueError('未能计算音频指纹')
    return data
