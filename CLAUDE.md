# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

BaseUwU is a single-header C library implementing a binary-to-text encoding scheme where each input bit is encoded as either `OwO` (0) or `UwU` (1), producing 24 output bytes per input byte. It is intentionally maximally inefficient.

## Build & Run

Compile and run the test program:

```sh
clang -Wno-pointer-sign -o test.exe test.c && ./test.exe
```

There is no automated test framework — `test.c` is the test program. Running the compiled binary is how you verify correctness.

## Architecture

`baseuwu.h` is the entire library — a single STB-style header. It contains:

- **Public declarations** at the top (always compiled)
- **Implementation** guarded by `#ifdef BASE_UWU_IMPLEMENTATION` (compiled only in one translation unit that defines that macro before `#include "baseuwu.h"`)

`test.c` is the sole consumer and shows correct usage: define `BASE_UWU_IMPLEMENTATION` before including the header.

## API

| Function | Signature | Returns |
|----------|-----------|---------|
| `UwU_Encode` | `(size_t input_size, const uint8_t *input_data, char **output_data_pointer)` | `0` success, `1` alloc failure |
| `UwU_Decode` | `(const char *input_data, size_t *output_size_ptr, const uint8_t **output_data_ptr)` | `0` success, `1` alloc failure, `2` invalid input |
| `UwU_Validate` | `(const char *input_data)` | `bool` |

All allocated output buffers must be freed by the caller.

## Conventions

- Functions are prefixed `UwU_`.
- Macros are `ALL_CAPS`: `BASE_UWU_IMPLEMENTATION`, `BASE_UWU_ALLOC(x)`.
- Custom allocator: define `BASE_UWU_ALLOC(x)` before including the implementation; defaults to `malloc`.
- The library avoids all standard library functions in the implementation except `malloc` (via the configurable macro), making it embeddable without stdlib if `BASE_UWU_ALLOC` is overridden.
- `-Wno-pointer-sign` is required because the API mixes `char *` and `uint8_t *` intentionally.
