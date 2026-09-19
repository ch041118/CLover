"""Isolated, time-limited CPU speech worker. Receives audio over stdin, writes only JSON."""
import io
import json
import sys

def main():
    import av
    import numpy as np
    from faster_whisper import WhisperModel
    raw=sys.stdin.buffer.read(2_000_001)
    if len(raw)>2_000_000: raise ValueError('size')
    chunks=[];count=0
    resampler=av.AudioResampler(format='s16',layout='mono',rate=16000)
    with av.open(io.BytesIO(raw)) as container:
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                values=converted.to_ndarray().flatten();count+=len(values)
                if count>45*16000: raise ValueError('duration')
                chunks.append(values)
        for converted in resampler.resample(None):
            values=converted.to_ndarray().flatten();count+=len(values)
            if count>45*16000: raise ValueError('duration')
            chunks.append(values)
    if not chunks: print(json.dumps({'text':''}));return
    audio=np.concatenate(chunks).astype(np.float32)/32768.0
    model=WhisperModel(sys.argv[1],device='cpu',compute_type='int8',cpu_threads=2,num_workers=1,local_files_only=True)
    segments,_=model.transcribe(audio,language='ko',beam_size=1,vad_filter=True,condition_on_previous_text=False)
    text=' '.join(s.text.strip() for s in segments if s.no_speech_prob<0.6 and s.avg_logprob>-1.0)
    print(json.dumps({'text':text},ensure_ascii=False))

if __name__=='__main__': main()
