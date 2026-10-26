"""Read and edit local audio tags without replacing the audio content."""
from functools import lru_cache
import os
import re
from pathlib import Path
import shutil
import tempfile
import base64
import struct

import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TALB
from mutagen.mp4 import MP4
from mutagen.asf import ASF
from mutagen.id3 import TPE2, TDRC, TRCK, TPOS, TCON, TCOM, COMM, USLT, APIC, TEXT, TLAN, TCOP, TPUB, TIT1, TBPM, TSRC
from mutagen.mp4 import MP4Cover, MP4FreeForm
from mutagen.flac import FLAC, Picture

TAG_FIELDS = ('title', 'artist', 'album', 'album_artist', 'date', 'track_number', 'disc_number', 'genre', 'composer', 'comment',
              'lyricist', 'language', 'copyright', 'publisher', 'grouping', 'bpm', 'isrc')
ID3_FIELDS = ('TIT2', 'TPE1', 'TALB', 'TPE2', 'TDRC', 'TRCK', 'TPOS', 'TCON', 'TCOM', 'COMM', 'TEXT', 'TLAN', 'TCOP', 'TPUB', 'TIT1', 'TBPM', 'TSRC')
MP4_FIELDS = ('\xa9nam', '\xa9ART', '\xa9alb', 'aART', '\xa9day', 'trkn', 'disk', '\xa9gen', '\xa9wrt', '\xa9cmt',
              '----:com.apple.iTunes:LYRICIST', '----:com.apple.iTunes:LANGUAGE', 'cprt', '----:com.apple.iTunes:LABEL',
              '\xa9grp', 'tmpo', '----:com.apple.iTunes:ISRC')
ASF_FIELDS = ('Title', 'Author', 'WM/AlbumTitle', 'WM/AlbumArtist', 'WM/Year', 'WM/TrackNumber', 'WM/PartOfSet', 'WM/Genre', 'WM/Composer', 'Description',
              'WM/Writer', 'WM/Language', 'Copyright', 'WM/Publisher', 'WM/ContentGroupDescription', 'WM/BeatsPerMinute', 'WM/ISRC')
VORBIS_FIELDS = ('title', 'artist', 'album', 'albumartist', 'date', 'tracknumber', 'discnumber', 'genre', 'composer', 'comment',
                 'lyricist', 'language', 'copyright', 'organization', 'grouping', 'bpm', 'isrc')


def field_keys(audio):
    return ID3_FIELDS if isinstance(audio.tags, ID3) else MP4_FIELDS if isinstance(audio, MP4) else ASF_FIELDS if isinstance(audio, ASF) else VORBIS_FIELDS

AUDIO_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.mp4', '.ogg', '.opus', '.wav', '.aac', '.aiff', '.aif', '.wma', '.ape', '.wv'}
MEDIA_TYPES = {'.mp3': 'audio/mpeg', '.flac': 'audio/flac', '.m4a': 'audio/mp4', '.mp4': 'audio/mp4', '.ogg': 'audio/ogg', '.opus': 'audio/ogg', '.wav': 'audio/wav', '.aac': 'audio/aac'}


def download_stem(title, artist):
    def clean(value, fallback):
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', str(value or '')).strip(' .')
        value = value.encode('utf-8')[:100].decode('utf-8', errors='ignore').rstrip(' .')
        return value or fallback
    stem = clean(title, '未知歌曲') + ' - ' + clean(artist, '未知歌手')
    if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]', stem.split('.')[0], re.I):
        stem = '_' + stem
    return stem


def tag_keys(audio):
    if isinstance(audio.tags, ID3):
        return ('TIT2', 'TPE1', 'TALB')
    if isinstance(audio, MP4):
        return ('\xa9nam', '\xa9ART', '\xa9alb')
    if isinstance(audio, ASF):
        return ('Title', 'Author', 'WM/AlbumTitle')
    return ('title', 'artist', 'album')


def text_tag(tags, key):
    value = (tags or {}).get(key, '')
    if not value and isinstance(tags, ID3):
        frames = tags.getall(key)
        value = frames[0] if frames else ''
    if hasattr(value, 'text'):
        value = value.text
    if isinstance(value, (list, tuple)):
        return ' / '.join(item.decode('utf-8', errors='replace') if isinstance(item, bytes) else str(item) for item in value)
    return str(value)


def audio_cover(audio):
    if not audio:
        return None
    if isinstance(audio.tags, ID3):
        pictures = audio.tags.getall('APIC')
        if pictures:
            return pictures[0].data, pictures[0].mime
    if isinstance(audio, MP4) and audio.tags and audio.tags.get('covr'):
        cover = audio.tags['covr'][0]
        return bytes(cover), 'image/png' if cover.imageformat == 14 else 'image/jpeg'
    pictures = getattr(audio, 'pictures', [])
    if pictures:
        return pictures[0].data, pictures[0].mime
    if audio.tags and audio.tags.get('metadata_block_picture'):
        try:
            picture = Picture(base64.b64decode(audio.tags['metadata_block_picture'][0]))
            return picture.data, picture.mime
        except (ValueError, mutagen.MutagenError):
            pass
    if isinstance(audio, ASF) and audio.tags and audio.tags.get('WM/Picture'):
        try:
            data = audio.tags['WM/Picture'][0].value
            length = struct.unpack_from('<I', data, 1)[0]
            offset = 5
            strings = []
            for _ in range(2):
                end = offset
                while data[end:end + 2] != b'\0\0' and end < len(data):
                    end += 2
                strings.append(data[offset:end].decode('utf-16-le'))
                offset = end + 2
            return data[offset:offset + length], strings[0]
        except (ValueError, struct.error, AttributeError):
            pass
    return None


@lru_cache(maxsize=4096)
def read_metadata(filename, modified_ns, size):
    result = {**dict.fromkeys(TAG_FIELDS, ''), 'title': Path(filename).stem, 'duration': 0,
              'bitrate': None, 'has_cover': False, 'editable': False}
    try:
        audio = mutagen.File(filename)
        if audio is None:
            return result
        tagged = []
        for field, key in zip(TAG_FIELDS, field_keys(audio)):
            value = text_tag(audio.tags, key)
            if isinstance(audio, MP4) and field in {'track_number', 'disc_number'} and audio.tags and audio.tags.get(key):
                number, total = audio.tags[key][0]
                value = f'{number}/{total}' if total else str(number)
            result[field] = value or result[field]
            if value:
                tagged.append(field)
        result.update(duration=float(audio.info.length), bitrate=getattr(audio.info, 'bitrate', None),
                      has_cover=bool(audio_cover(audio)), editable=hasattr(audio, 'add_tags'), tagged_fields=tagged,
                      sample_rate=getattr(audio.info, 'sample_rate', None), channels=getattr(audio.info, 'channels', None),
                      bits_per_sample=getattr(audio.info, 'bits_per_sample', None))
    except (OSError, mutagen.MutagenError, ValueError):
        pass
    return result


def update_metadata(path, title, artist, album):
    write_metadata(path, {'title': title, 'artist': artist, 'album': album})


def write_metadata(path, changes, *, lyrics=None, cover=None, clear_all=False):
    # Save to a sibling copy and replace only after tag writing succeeds, so a
    # failed edit leaves the original audio and its other tags intact.
    fd, filename = tempfile.mkstemp(prefix='.melokeep-tags-', suffix=path.suffix, dir=path.parent)
    os.close(fd)
    temporary = Path(filename)
    try:
        shutil.copy2(path, temporary)
        audio = mutagen.File(temporary)
        if audio is None or not hasattr(audio, 'add_tags'):
            raise ValueError('此文件格式不支持编辑标签')
        if audio.tags is None:
            audio.add_tags()
        if clear_all:
            audio.tags.clear()
            if isinstance(audio, FLAC): audio.clear_pictures()
        frames = (TIT2, TPE1, TALB, TPE2, TDRC, TRCK, TPOS, TCON, TCOM, COMM, TEXT, TLAN, TCOP, TPUB, TIT1, TBPM, TSRC)
        for field, key, frame in zip(TAG_FIELDS, field_keys(audio), frames):
            if field not in changes:
                continue
            value = str(changes[field] or '').strip()
            if isinstance(audio.tags, ID3):
                audio.tags.delall(key)
                if value:
                    audio.tags.add(frame(encoding=3, text=[value], **({'lang': 'eng', 'desc': ''} if field == 'comment' else {})))
            elif isinstance(audio, MP4) and field in {'track_number', 'disc_number'} and value:
                numbers = value.split('/', 1)
                if not all(n.isdigit() and 0 <= int(n) <= 65535 for n in numbers):
                    raise ValueError('曲序和碟号应为数字，或数字/总数')
                audio.tags[key] = [(int(numbers[0]), int(numbers[1]) if len(numbers) > 1 else 0)]
            elif isinstance(audio, MP4) and key.startswith('----:') and value:
                audio.tags[key] = [MP4FreeForm(value.encode('utf-8'))]
            elif isinstance(audio, MP4) and field == 'bpm' and value:
                if not value.isdigit() or not 0 <= int(value) <= 65535:
                    raise ValueError('BPM 应为 0 到 65535 的整数')
                audio.tags[key] = [int(value)]
            elif value:
                audio.tags[key] = [value]
            elif key in audio.tags:
                del audio.tags[key]
        if lyrics is not None:
            if isinstance(audio.tags, ID3):
                audio.tags.delall('USLT')
                audio.tags.delall('SYLT')
                if lyrics:
                    audio.tags.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))
            else:
                audio.tags['\xa9lyr' if isinstance(audio, MP4) else 'WM/Lyrics' if isinstance(audio, ASF) else 'lyrics'] = [lyrics]
        if cover is False:
            if isinstance(audio.tags, ID3): audio.tags.delall('APIC')
            elif isinstance(audio, FLAC): audio.clear_pictures()
            else:
                for key in ('covr', 'metadata_block_picture', 'WM/Picture', 'coverart'):
                    if key in audio.tags: del audio.tags[key]
        elif cover:
            content, mime = cover
            if isinstance(audio.tags, ID3):
                audio.tags.delall('APIC')
                audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc='Cover', data=content))
            elif isinstance(audio, MP4):
                audio.tags['covr'] = [MP4Cover(content, imageformat=MP4Cover.FORMAT_PNG if mime == 'image/png' else MP4Cover.FORMAT_JPEG)]
            else:
                picture = Picture()
                picture.type, picture.mime, picture.data = 3, mime, content
                if isinstance(audio, FLAC):
                    audio.clear_pictures()
                    audio.add_picture(picture)
                elif isinstance(audio, ASF):
                    audio.tags['WM/Picture'] = [mutagen.asf.ASFByteArrayAttribute(
                        struct.pack('<BI', 3, len(content)) + mime.encode('utf-16-le') + b'\0\0\0\0' + content)]
                else:
                    audio.tags['metadata_block_picture'] = [base64.b64encode(picture.write()).decode('ascii')]
        audio.save()
        if mutagen.File(temporary) is None:
            raise ValueError('写入后的音频无法读取')
        os.replace(temporary, path)
        read_metadata.cache_clear()
    finally:
        temporary.unlink(missing_ok=True)


def read_lyrics(path, *, prefer_sidecar=True):
    sidecar = path.with_suffix('.lrc')
    if prefer_sidecar and sidecar.is_file() and not sidecar.is_symlink():
        return sidecar.read_text(encoding='utf-8-sig', errors='replace')
    audio = mutagen.File(path)
    if audio is None:
        return ''
    if isinstance(audio.tags, ID3):
        for frame in audio.tags.getall('SYLT'):
            # Format 2 stores milliseconds; MPEG-frame timestamps need a decoder.
            if frame.format == 2 and frame.type == 1 and frame.text:
                return '\n'.join(f'[{timestamp // 60000:02}:{timestamp // 1000 % 60:02}.{timestamp % 1000:03}]{text}'
                                 for text, timestamp in frame.text)
        frames = audio.tags.getall('USLT')
        return str(frames[0].text) if frames else ''
    return text_tag(audio.tags, '\xa9lyr' if isinstance(audio, MP4) else 'WM/Lyrics' if isinstance(audio, ASF) else 'lyrics')
