"""Run once while online, before handling personal data. Runtime is offline-only."""
from pathlib import Path
from huggingface_hub import snapshot_download
path=Path(__file__).resolve().parent/'models'/'whisper-tiny'
snapshot_download('Systran/faster-whisper-tiny',local_dir=str(path),
                  allow_patterns=['model.bin','config.json','tokenizer.json','vocabulary.*','preprocessor_config.json'])
print('Speech model prepared at',path)
print('Set SPEECH_ENABLED=true and SPEECH_MODEL_PATH=./models/whisper-tiny in backend/.env.')
