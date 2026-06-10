"""Minimal Wyoming wake server using the ORIGINAL openwakeword (onnx) runtime."""
import argparse, asyncio, logging, time
from functools import partial
from pathlib import Path
import numpy as np
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.info import Attribution, Describe, Info, WakeModel, WakeProgram
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.wake import Detect, Detection, NotDetected
from openwakeword.model import Model

_LOGGER = logging.getLogger("oww_wyoming")
SAMPLES = 1280
NBYTES = SAMPLES * 2  # 16-bit mono


class Handler(AsyncEventHandler):
    def __init__(self, models, threshold, trigger_level, refractory, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.models = models  # {stem: path}
        self.threshold = threshold
        self.trigger_level = trigger_level
        self.refractory = refractory
        self.converter = AudioChunkConverter(rate=16000, width=2, channels=1)
        self.buf = b""
        self.oww = None
        self.active = set()
        self.triggers = {}
        self.last_trig = {}
        self.detected = False
        self.ts = 0

    def _ensure(self):
        if self.oww is None:
            self.oww = Model(wakeword_model_paths=list(self.models.values()))

    async def handle_event(self, event):
        if Describe.is_type(event.type):
            await self.write_event(self._info().event())
            return True
        if Detect.is_type(event.type):
            d = Detect.from_event(event)
            req = set(d.names) if d.names else set(self.models)
            self.active = (req & set(self.models)) or set(self.models)
            self._ensure()
            _LOGGER.debug("Detect: active=%s", self.active)
            return True
        if AudioStart.is_type(event.type):
            self._ensure()
            self.buf = b""; self.detected = False; self.ts = 0
            self.triggers = {n: self.trigger_level for n in self.active}
            self.last_trig = {}
            try: self.oww.reset()
            except Exception: pass
            return True
        if AudioChunk.is_type(event.type):
            chunk = self.converter.convert(AudioChunk.from_event(event))
            self.buf += chunk.audio
            while len(self.buf) >= NBYTES:
                frame = self.buf[:NBYTES]; self.buf = self.buf[NBYTES:]
                self.ts += 80
                preds = self.oww.predict(np.frombuffer(frame, dtype=np.int16))
                now = time.monotonic()
                for name in list(self.active):
                    score = float(preds.get(name, 0.0))
                    if score <= self.threshold:
                        continue
                    lt = self.last_trig.get(name)
                    if lt is not None and (now - lt) < self.refractory:
                        continue
                    self.triggers[name] = self.triggers.get(name, self.trigger_level) - 1
                    if self.triggers[name] > 0:
                        continue
                    self.triggers[name] = self.trigger_level
                    self.last_trig[name] = now
                    self.detected = True
                    _LOGGER.info("Detected '%s' (score=%.3f)", name, score)
                    await self.write_event(Detection(name=name, timestamp=self.ts).event())
            return True
        if AudioStop.is_type(event.type):
            if not self.detected:
                await self.write_event(NotDetected().event())
            return True
        return True

    def _info(self):
        models = [WakeModel(name=n, description=n.replace("_", " "),
                            phrase=n.replace("_", " "),
                            attribution=Attribution(name="", url=""),
                            installed=True, languages=[], version="")
                  for n in self.models]
        return Info(wake=[WakeProgram(name="openwakeword",
                    description="original openWakeWord (onnx)",
                    attribution=Attribution(name="dscripka", url="https://github.com/dscripka/openWakeWord"),
                    installed=True, version="orig", models=models)])


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--uri", default="tcp://0.0.0.0:10400")
    p.add_argument("--custom-model-dir", required=True)
    p.add_argument("--preload-model", action="append", default=[])
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--trigger-level", type=int, default=1)
    p.add_argument("--refractory-seconds", type=float, default=2.0)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    d = Path(args.custom_model_dir)
    stems = args.preload_model or [f.stem for f in d.glob("*.onnx")]
    models = {}
    for s in stems:
        f = d / f"{s}.onnx"
        if f.exists():
            models[s] = str(f)
    if not models:
        raise SystemExit(f"No .onnx models for {stems} in {d}")
    _LOGGER.info("Loaded models: %s", models)
    server = AsyncServer.from_uri(args.uri)
    _LOGGER.info("Ready")
    await server.run(partial(Handler, models, args.threshold, args.trigger_level, args.refractory_seconds))


if __name__ == "__main__":
    asyncio.run(main())
