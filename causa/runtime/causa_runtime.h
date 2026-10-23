/*
 * CAUSA runtime interface (compiler-architecture §6).
 *
 * Implemented in this header: value representation, metadata table types,
 * checked arithmetic, stream setup and base-execution runtime error reporting.
 * A program containing only `input` and `let` statements needs nothing else.
 *
 * Implemented in causa_runtime.c (link it with the generated C): value
 * formatting, causa_show, causa_explain, causa_impact, causa_whatif and
 * causa_assert.
 *
 * Requirements: C99, 64-bit IEEE 754 doubles evaluated in double precision
 * (FLT_EVAL_METHOD == 0), round-to-nearest.
 */
#ifndef CAUSA_RUNTIME_H
#define CAUSA_RUNTIME_H

#include <float.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#if defined(FLT_EVAL_METHOD) && FLT_EVAL_METHOD != 0
#error "CAUSA requires FLT_EVAL_METHOD == 0 (double arithmetic in double precision)"
#endif
typedef char causa_double_is_64_bits[(sizeof(double) == 8 && DBL_MANT_DIG == 53) ? 1 : -1];

/* ---- values ---------------------------------------------------------- */

/* One value per IR node. The static type of every node is in the metadata,
   so the union carries no tag. */
typedef union {
    int64_t i; /* CAUSA int */
    double f;  /* CAUSA float */
    bool b;    /* CAUSA bool */
} causa_value;

enum { CAUSA_TYPE_INT = 0, CAUSA_TYPE_FLOAT = 1, CAUSA_TYPE_BOOL = 2 };
enum { CAUSA_KIND_INPUT = 0, CAUSA_KIND_LET = 1 };
enum { CAUSA_NODE_INPUT = 0, CAUSA_NODE_CONST = 1, CAUSA_NODE_OP = 2, CAUSA_NODE_BIND = 3 };

/* Error codes: 0 = success; R101-R103 as in language-specification §6.6. */
enum {
    CAUSA_OK = 0,
    CAUSA_INTERNAL_ERROR = 1, /* a compiler bug, never a CAUSA program error */
    CAUSA_R101 = 101,         /* division by zero */
    CAUSA_R102 = 102,         /* integer overflow */
    CAUSA_R103 = 103          /* non-finite float result */
};

/* A runtime error and the location of the failing operator. */
typedef struct {
    int code;
    int line;
    int column;
} causa_error;

/* ---- metadata tables (emitted by the compiler) ------------------------ */

/* Owner of a node: a binding index (>= 0), or CAUSA_ASSERT_OWNER(k) for the
   k-th assert statement (0-based). */
#define CAUSA_ASSERT_OWNER(k) (-1 - (k))
#define CAUSA_NO_TARGET (-1)

typedef struct {
    int id;            /* node ID (IDs retired by the optimizer are absent) */
    int kind;          /* CAUSA_NODE_* */
    int type;          /* CAUSA_TYPE_* */
    int owner;         /* binding index or CAUSA_ASSERT_OWNER(k) */
    int line, column;  /* source location (compiler-architecture §3.5) */
    int operand_count; /* 0, 1 or 2 */
    int operands[2];   /* node IDs this node uses; -1 if unused */
} causa_node_info;

typedef struct {
    const char *name;
    int kind;                /* CAUSA_KIND_* */
    int type;                /* CAUSA_TYPE_* */
    int anchor;              /* node ID of the input or bind node */
    int line, column;        /* the declared name */
    const char *source_text; /* let expression as written; NULL for inputs */
    int dep_count;           /* direct dependencies, declaration order */
    const int *deps;         /* binding indices */
    int ref_count;           /* the same set in first-appearance order (explain children) */
    const int *refs;
    int dependent_count;     /* derived reverse index, declaration order */
    const int *dependents;
} causa_binding_info;

typedef struct {
    int line, column;        /* the assert keyword */
    const char *source_text; /* the condition as written */
    int root;                /* node ID holding the bool condition */
    int ref_count;           /* bindings referenced, first-appearance order */
    const int *refs;
} causa_assert_info;

typedef struct {
    const char *source_file;
    int node_slots; /* highest node ID + 1: size of a value environment */
    int node_count;
    const causa_node_info *nodes; /* ascending ID */
    int binding_count;
    const causa_binding_info *bindings; /* declaration order */
    int assert_count;
    const causa_assert_info *asserts;
} causa_program_info;

/* ---- provided by generated code --------------------------------------- */

extern const causa_program_info CAUSA_PROGRAM;

/* Compute env[node_id] from env[operands]. Returns 0, or an error code after
   filling *err. Never exits and never writes any other slot. */
int causa_eval_node(int node_id, causa_value *env, causa_error *err);

/* ---- checked arithmetic (implemented) --------------------------------- */
/* Each returns 0 and stores the result, or returns an error code and leaves
   *out untouched. No signed overflow or other undefined behavior occurs. */

static inline int causa_add_i64(int64_t a, int64_t b, int64_t *out)
{
    if ((b > 0 && a > INT64_MAX - b) || (b < 0 && a < INT64_MIN - b)) return CAUSA_R102;
    *out = a + b;
    return CAUSA_OK;
}

static inline int causa_sub_i64(int64_t a, int64_t b, int64_t *out)
{
    if ((b < 0 && a > INT64_MAX + b) || (b > 0 && a < INT64_MIN + b)) return CAUSA_R102;
    *out = a - b;
    return CAUSA_OK;
}

static inline int causa_mul_i64(int64_t a, int64_t b, int64_t *out)
{
    if (a > 0) {
        if (b > 0) { if (a > INT64_MAX / b) return CAUSA_R102; }
        else if (b < INT64_MIN / a) return CAUSA_R102;
    } else if (a < 0) {
        if (b > 0) { if (a < INT64_MIN / b) return CAUSA_R102; }
        else if (b < INT64_MAX / a) return CAUSA_R102;
    }
    *out = a * b;
    return CAUSA_OK;
}

static inline int causa_neg_i64(int64_t a, int64_t *out)
{
    if (a == INT64_MIN) return CAUSA_R102;
    *out = -a;
    return CAUSA_OK;
}

static inline int causa_finite(double r, double *out)
{
    if (!isfinite(r)) return CAUSA_R103;
    *out = r;
    return CAUSA_OK;
}

static inline int causa_add_f64(double a, double b, double *out) { return causa_finite(a + b, out); }
static inline int causa_sub_f64(double a, double b, double *out) { return causa_finite(a - b, out); }
static inline int causa_mul_f64(double a, double b, double *out) { return causa_finite(a * b, out); }

static inline int causa_div_f64(double a, double b, double *out)
{
    if (b == 0.0) return CAUSA_R101; /* also true for -0.0 */
    return causa_finite(a / b, out);
}

/* Record an error location when `code` is nonzero; returns `code`. */
static inline int causa_check(int code, int line, int column, causa_error *err)
{
    if (code != CAUSA_OK) {
        err->code = code;
        err->line = line;
        err->column = column;
    }
    return code;
}

/* ---- streams ------------------------------------------------------------ */

/* Called first by every generated main: output lines must end in a single
   line feed (language-specification §9.1), so Windows text-mode translation
   to CR LF is switched off. */
static inline void causa_init(void)
{
#ifdef _WIN32
    _setmode(_fileno(stdout), _O_BINARY);
    _setmode(_fileno(stderr), _O_BINARY);
#endif
}

/* ---- base-execution runtime errors (implemented) ---------------------- */

static inline const char *causa_error_description(int code)
{
    switch (code) {
    case CAUSA_R101: return "division by zero";
    case CAUSA_R102: return "integer overflow";
    case CAUSA_R103: return "non-finite float result";
    default: return "internal compiler error";
    }
}

/* language-specification §9.3: report and exit with status 2. */
static inline void causa_runtime_error(const causa_error *err)
{
    fflush(stdout);
    if (err->code >= CAUSA_R101 && err->code <= CAUSA_R103)
        fprintf(stderr, "%s:%d:%d: runtime error[R%d]: %s\n", CAUSA_PROGRAM.source_file,
                err->line, err->column, err->code, causa_error_description(err->code));
    else
        fprintf(stderr, "%s: internal compiler error (code %d)\n", CAUSA_PROGRAM.source_file, err->code);
    exit(2);
}

/* ---- runtime library (causa_runtime.c) ---------------------------------- */
/* All take the base environment read-only and write only to stdout, except
   causa_assert, which reports a failure on stderr and exits with status 1. */

#define CAUSA_VALUE_BUFSIZE 48
/* Format a value as language-specification §8.2 requires (floats exactly as
   Python's repr). `out` should hold CAUSA_VALUE_BUFSIZE bytes. */
void causa_format_value(int type, causa_value value, char *out, size_t size);

void causa_show(const causa_value *env, int binding);
void causa_explain(const causa_value *env, int binding);
void causa_impact(const causa_value *env, int binding, int visible);
/* `value` already has the input's type; target is CAUSA_NO_TARGET for the full form. */
void causa_whatif(const causa_value *env, int input_binding, causa_value value, int target_binding,
                  int visible);
/* Exits with status 1 and a diagnostic if !ok. */
void causa_assert(const causa_value *env, int assert_index, bool ok);

#endif /* CAUSA_RUNTIME_H */
