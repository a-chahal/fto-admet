# t07-core-dispatch - `core/dispatch.py` (run ONE model, generically)

**Kind:** core · **Autonomy:** review · **Runs:** laptop to author + test (mocked subprocess)
**Touch only:** `core/dispatch.py`, `tests/test_dispatch.py`
**Deps:** t04-core-registry, t03-core-schemas, t05-core-gpu, t06-core-ledger

## Read first
- `CLAUDE.md` §2 (contract: core shells out, cannot import models), §1 (fresh-shell / GPU-in-same-connection).
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §6 (`dispatch.run_model` spec), §7 (GPU + ledger).

## Build
The **only** place that shells out. Runs exactly one model in its isolated env; generic and singular
(does not grow with the number of models).

1. **`run_model(name: ModelName, input, output_dir) -> OutputRecord`:**
   - Look up `spec = REGISTRY[name]`. Validate `input` against `spec.input_schema` **before** launching.
   - If `spec.requires_gpu`: ask `gpu.pick_free_gpu()`; if `None`, either wait/retry or raise a clear
     "no GPU available" error (document the choice). The device is used in the *same* command.
   - Shell out: `pixi run --manifest-path <spec.env_manifest> python <spec.entrypoint>
     --input <in> --output <out>` (+ `--gpu N` when applicable). For GPU jobs compose it as a single
     invocation with `CUDA_VISIBLE_DEVICES=N` set in that same call (mirrors the one-ssh-connection rule).
   - Collect the output file, validate against `spec.output_schema`, return an `OutputRecord`.
   - Write a `ledger.append(...)` record (`status=ok`), including `env_lock_hash` + `input_hash`.
2. **Failure handling:** env won't resolve, subprocess non-zero, or output missing/invalid → raise a
   structured `DispatchError` **and** write a ledger record with `status=fail` + the reason. Never swallow.
3. `env_manifest is None` (web-only / out-of-band models) → `run_model` refuses with a clear message that
   these run via their README SOP, not the bulk loop.

## Landmines
- **core must not import any model.** It only builds a command string and runs a subprocess.
- GPU device selection and the job must ride the **same** shell invocation (env var can't span calls).
- Validate input before spawning and output after collecting - a wrong-unit output must fail validation,
  not silently propagate.

## Done (gate: `pixi run pytest tests/test_dispatch.py -q` green - subprocess mocked, no real model)
- `run_model` validates input, builds the correct `pixi run --manifest-path … python … --input … --output …`
  command (assert the string), and appends an `ok` ledger record on success.
- A non-zero subprocess (mocked) → `DispatchError` raised **and** a `fail` ledger record written.
- A model with `env_manifest=None` → refused with the SOP message.
- A GPU model (mocked `pick_free_gpu`) includes the device in the invocation; `None` device is handled.

## Blocked if
- Laptop-only with mocks; should not block. Record any error and BLOCK.
