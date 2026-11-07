"""The few calls Auto Seek needs from ONNX Runtime's C API, through ctypes.

ONNX Runtime ships as one shared library per platform (downloaded on first
use; see ``auto_seek.RUNTIMES``), and its C API is a table of function
pointers that only ever grows, so a fixed position names the same function in
every release since the one in ``API_VERSION``. That keeps the plugin free of
compiled code of its own and of Python packages Stash's Python may not have.

One session scores one frame at a time: with int8 weights, activations are
quantised per call, so a batch would score each frame slightly differently
from scoring it alone, and batching measured no faster on one thread.
"""

import ctypes

API_VERSION = 17  # everything used below exists since ONNX Runtime 1.17

# Positions in the OrtApi table (onnxruntime_c_api.h).
GET_ERROR_MESSAGE = 2
CREATE_ENV = 3
CREATE_SESSION_FROM_ARRAY = 8
RUN = 9
CREATE_SESSION_OPTIONS = 10
SET_INTRA_OP_THREADS = 24
SET_INTER_OP_THREADS = 25
CREATE_TENSOR_WITH_DATA = 49
GET_TENSOR_MUTABLE_DATA = 51
CREATE_CPU_MEMORY_INFO = 69
RELEASE_STATUS = 93
RELEASE_VALUE = 96
RELEASE_SESSION_OPTIONS = 100

LOG_ERROR = 3
TENSOR_FLOAT = 1
TENSOR_UINT8 = 2

FRAME_SIZE = 224
FRAME_BYTES = FRAME_SIZE * FRAME_SIZE * 3

_P = ctypes.c_void_p


class Session:
    """A model taking ``pixels`` (uint8, N x 224 x 224 x 3 RGB) and ``q`` (float,
    N x 3 position features), returning ``started`` (N) and ``acts`` (N x A)."""

    def __init__(self, library: str, model: bytes, threads: int = 1, acts: int = 10):
        self._lib = ctypes.CDLL(library)
        self._lib.OrtGetApiBase.restype = _P
        base = ctypes.cast(self._lib.OrtGetApiBase(), ctypes.POINTER(_P))
        api = ctypes.CFUNCTYPE(_P, ctypes.c_uint32)(base[0])(API_VERSION)
        if not api:
            raise RuntimeError("The ONNX Runtime library is older than 1.17")
        self._table = ctypes.cast(api, ctypes.POINTER(_P))
        self._acts = acts
        self._message = self._fn(GET_ERROR_MESSAGE, ctypes.c_char_p, _P)
        self._release_status = self._fn(RELEASE_STATUS, None, _P)
        self._release_value = self._fn(RELEASE_VALUE, None, _P)
        out = ctypes.POINTER(_P)

        self._env = _P()
        self._check(
            self._fn(CREATE_ENV, _P, ctypes.c_int, ctypes.c_char_p, out)(
                LOG_ERROR, b"auto-seek", ctypes.byref(self._env)
            )
        )
        options = _P()
        self._check(self._fn(CREATE_SESSION_OPTIONS, _P, out)(ctypes.byref(options)))
        try:
            self._check(
                self._fn(SET_INTRA_OP_THREADS, _P, _P, ctypes.c_int)(options, max(1, threads))
            )
            self._check(self._fn(SET_INTER_OP_THREADS, _P, _P, ctypes.c_int)(options, 1))
            # From memory rather than a path: paths are wide strings on Windows.
            buffer = ctypes.create_string_buffer(model, len(model))
            self._session = _P()
            create = self._fn(CREATE_SESSION_FROM_ARRAY, _P, _P, _P, ctypes.c_size_t, _P, out)
            self._check(create(self._env, buffer, len(model), options, ctypes.byref(self._session)))
        finally:
            self._fn(RELEASE_SESSION_OPTIONS, None, _P)(options)
        self._memory = _P()
        self._check(
            self._fn(CREATE_CPU_MEMORY_INFO, _P, ctypes.c_int, ctypes.c_int, out)(
                0, 0, ctypes.byref(self._memory)
            )
        )
        self._tensor = self._fn(
            CREATE_TENSOR_WITH_DATA, _P, _P, _P, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_int64), ctypes.c_size_t, ctypes.c_int, out,
        )  # fmt: skip
        names = ctypes.POINTER(ctypes.c_char_p)
        self._run = self._fn(
            RUN, _P, _P, _P, names, out, ctypes.c_size_t, names, ctypes.c_size_t, out
        )
        self._data = self._fn(GET_TENSOR_MUTABLE_DATA, _P, _P, out)

    def _fn(self, index: int, result, *arguments):
        return ctypes.CFUNCTYPE(result, *arguments)(self._table[index])

    def _check(self, status) -> None:
        if status:
            message = (self._message(status) or b"").decode("utf-8", "replace")
            self._release_status(status)
            raise RuntimeError(f"ONNX Runtime: {message}")

    def _value(self, buffer, shape: tuple[int, ...], kind: int):
        dims = (ctypes.c_int64 * len(shape))(*shape)
        value = _P()
        self._check(
            self._tensor(
                self._memory,
                ctypes.cast(buffer, _P),
                ctypes.sizeof(buffer),
                dims,
                len(shape),
                kind,
                ctypes.byref(value),
            )
        )
        return value

    def score(self, pixels: bytes, features: list[float]) -> tuple[float, list[float]]:
        """One frame: the chance the action has started, and the act shares."""
        if len(pixels) != FRAME_BYTES:
            raise ValueError("a frame must be 224 x 224 RGB")
        image = (ctypes.c_uint8 * FRAME_BYTES).from_buffer_copy(pixels)
        position = (ctypes.c_float * 3)(*features)
        inputs = (_P * 2)(
            self._value(image, (1, FRAME_SIZE, FRAME_SIZE, 3), TENSOR_UINT8),
            self._value(position, (1, 3), TENSOR_FLOAT),
        )
        outputs = (_P * 2)()
        try:
            self._check(
                self._run(
                    self._session, None,
                    (ctypes.c_char_p * 2)(b"pixels", b"q"), inputs, 2,
                    (ctypes.c_char_p * 2)(b"started", b"acts"), 2, outputs,
                )
            )  # fmt: skip
            started = self._floats(outputs[0], 1)[0]
            return started, self._floats(outputs[1], self._acts)
        finally:
            for value in (*inputs, *outputs):
                if value:
                    self._release_value(value)

    def _floats(self, value, count: int) -> list[float]:
        pointer = _P()
        self._check(self._data(value, ctypes.byref(pointer)))
        array = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_float))
        return [float(array[i]) for i in range(count)]
