#!/usr/bin/env python3
"""Download pinned, checksum-verified local models. Never runs during recording."""

import argparse
import hashlib
from pathlib import Path
import shutil
import tarfile
import tempfile
import time
from urllib.request import urlopen

from listening_models import SPEECH_MODEL, SOUND_MODEL


BASE_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/'
BUNDLES = [
    ('asr-models/' + SPEECH_MODEL + '.tar.bz2',
     '455f40e556aa2b20ac9d3bffd603b58002075c1193b4070938540c11efe0a4da', {
         SPEECH_MODEL + '/tokens.txt': '49e3c2646595fd907228b3c6787069658f67b17377c60aeb8619c4551b2316fb',
         SPEECH_MODEL + '/encoder-epoch-99-avg-1.int8.onnx': '32c98281c7bd8b63e3e142d007251b37f120572e8fdea9a4f5a79ce22b10ec4f',
         SPEECH_MODEL + '/decoder-epoch-99-avg-1.onnx': '9da02b77cb08826756ec6a88635f35a40374e4164e7c6359121a9145958a6ceb',
         SPEECH_MODEL + '/joiner-epoch-99-avg-1.int8.onnx': '831477d390e59a61f1b6a6f763b9903e6c6366ff6034f1ddba613be82637122f',
     }),
    ('audio-tagging-models/' + SOUND_MODEL + '.tar.bz2',
     '07e2fafcdcbc461f2816188d9b0bbafced12584030cf67d5652e549ef256a2c6', {
         SOUND_MODEL + '/model.int8.onnx': '69304b8a1b96bbe6b7d16c24079f0732c65faf3568a14cb82a8238c709afe76c',
         SOUND_MODEL + '/class_labels_indices.csv': 'cdd1049833c4b86127c2773ac0d14a2754b6a6d0d1798002ed5c66e699708429',
     }),
]
DENOISER_HASH = 'e77603ac0c23dac3227dd2d7135b3a585cbee2679048aecfa886657d3ae1b534'


def checksum(path):
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download(relative, destination, expected):
    started = time.monotonic()
    size = 0
    print('Downloading', relative, flush=True)
    with urlopen(BASE_URL + relative, timeout=30) as source, destination.open('wb') as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > 700 * 1024 * 1024 or time.monotonic() - started > 1200:
                raise RuntimeError('Model download exceeded its size or time limit.')
            output.write(chunk)
    if checksum(destination) != expected:
        raise RuntimeError('Model checksum mismatch; the existing installation was not replaced.')


def install_bundle(root, relative, archive_hash, files):
    if all(checksum(root / name) == expected for name, expected in files.items()):
        print('Verified', relative, flush=True)
        return
    with tempfile.TemporaryDirectory(prefix='.listening-install-', dir=root) as temporary:
        temporary = Path(temporary)
        archive = temporary / 'model.tar.bz2'
        download(relative, archive, archive_hash)
        with tarfile.open(archive, 'r:bz2') as bundle:
            for name, expected in files.items():
                member = bundle.getmember(name)
                if not member.isfile() or not 0 < member.size < 512 * 1024 * 1024:
                    raise RuntimeError('Unexpected model archive entry.')
                target = temporary / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
                if checksum(target) != expected:
                    raise RuntimeError('Extracted model checksum mismatch.')
        # Validate every required asset before replacing any existing asset.
        for name in files:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            (temporary / name).replace(target)
        print('Installed', relative, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models-dir', type=Path, default=Path(__file__).parent / 'models')
    parser.add_argument('--with-enhancement', action='store_true', help='Also install optional GTCRN noise reduction.')
    args = parser.parse_args()
    args.models_dir.mkdir(parents=True, exist_ok=True)
    for bundle in BUNDLES:
        install_bundle(args.models_dir, *bundle)
    if args.with_enhancement and checksum(args.models_dir / 'gtcrn_simple.onnx') != DENOISER_HASH:
        with tempfile.TemporaryDirectory(prefix='.listening-install-', dir=args.models_dir) as temporary:
            path = Path(temporary) / 'gtcrn_simple.onnx'
            download('speech-enhancement-models/gtcrn_simple.onnx', path, DENOISER_HASH)
            path.replace(args.models_dir / path.name)
    print('Local listening models ready. Set MICROPHONE_BACKEND=sherpa and restart Samson.')


if __name__ == '__main__':
    main()
