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
#include <stdarg.h>
#include <string.h>
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
    const char *file = CAUSA_PROGRAM.source_file ? CAUSA_PROGRAM.source_file : "<unknown>";
    fflush(stdout);
    if (err->code >= CAUSA_R101 && err->code <= CAUSA_R103)
        fprintf(stderr, "%s:%d:%d: runtime error[R%d]: %s\n", file,
                err->line, err->column, err->code, causa_error_description(err->code));
    else
        fprintf(stderr, "%s: internal compiler error (code %d)\n", file, err->code);
    exit(2);
}

/* ---- launch arguments (language-specification §9.5, implemented) -------- */
/* `--set NAME=VALUE`, repeatable, sets an input's base value before the first
   statement runs. Everything here is static inline so that header-only
   programs (inputs and lets only) accept launch arguments too. */

enum {
    CAUSA_A101 = 101, /* unknown option or stray argument */
    CAUSA_A102 = 102, /* --set without NAME=VALUE */
    CAUSA_A103 = 103, /* NAME is not a declared binding */
    CAUSA_A104 = 104, /* NAME is a let, not an input */
    CAUSA_A105 = 105, /* input set more than once */
    CAUSA_A106 = 106, /* VALUE is not a CAUSA literal */
    CAUSA_A107 = 107, /* VALUE's type does not fit the input */
    CAUSA_A108 = 108, /* integer magnitude exceeds 2^63 - 1 */
    CAUSA_A109 = 109  /* float rounds to infinity */
};

/* Launch values, one slot per binding; `set` is NULL when no --set was given.
   Function-local storage avoids an unused static object in other units. */
typedef struct {
    causa_value *values;
    unsigned char *set;
} causa_launch_state;

static inline causa_launch_state *causa_launch(void)
{
    static causa_launch_state state;
    return &state;
}

/* The base value of an input: its launch value if one was given, otherwise
   the source literal. Generated code calls this for every input node. */
static inline causa_value causa_input_value(int binding, causa_value source_default)
{
    const causa_launch_state *s = causa_launch();
    return (s->set && s->set[binding]) ? s->values[binding] : source_default;
}

/* Report an invalid launch argument (stderr) and exit with status 3. */
static inline void causa_argument_error(int code, const char *format, ...)
{
    va_list args;
    fflush(stdout);
    fprintf(stderr, "%s: argument error[A%d]: ",
            CAUSA_PROGRAM.source_file ? CAUSA_PROGRAM.source_file : "<unknown>", code);
    va_start(args, format);
    vfprintf(stderr, format, args);
    va_end(args);
    fputc('\n', stderr);
    exit(3);
}

/* Parse `text` with the rules of a source literal_value (LS §3.5, §5.4): "true",
   "false", or an optional "-" then an integer ("0" or no leading zero) or a
   float (digits "." digits, optional exponent). The whole string must match.
   Returns 0 and sets *type and *out, or CAUSA_A106 / A108 / A109. */
static inline int causa_parse_literal(const char *text, int *type, causa_value *out)
{
    const char *p = text, *int_start, *frac_start = NULL;
    size_t int_len, frac_len = 0;
    int negative = 0, exponent = 0, exp_negative = 0;
    if (strcmp(text, "true") == 0 || strcmp(text, "false") == 0) {
        *type = CAUSA_TYPE_BOOL;
        out->b = text[0] == 't';
        return CAUSA_OK;
    }
    if (*p == '-') { negative = 1; p++; }
    int_start = p;
    if (*p == '0') p++;
    else if (*p >= '1' && *p <= '9') while (*p >= '0' && *p <= '9') p++;
    else return CAUSA_A106; /* no digits */
    int_len = (size_t)(p - int_start);
    if (*p >= '0' && *p <= '9') return CAUSA_A106; /* leading zero */
    if (*p == '.') {
        p++;
        frac_start = p;
        while (*p >= '0' && *p <= '9') p++;
        frac_len = (size_t)(p - frac_start);
        if (frac_len == 0) return CAUSA_A106; /* "1." */
        if (*p == 'e' || *p == 'E') {
            p++;
            if (*p == '+' || *p == '-') exp_negative = *p++ == '-';
            if (!(*p >= '0' && *p <= '9')) return CAUSA_A106; /* exponent without digits */
            while (*p >= '0' && *p <= '9') {
                if (exponent < 100000) exponent = exponent * 10 + (*p - '0'); /* saturate: beyond any double */
                p++;
            }
        }
    }
    if (*p != '\0') return CAUSA_A106; /* anything else, e.g. "1e5", "+5", "0x10", " 1" */
    if (!frac_start) {
        uint64_t magnitude = 0;
        const char *d;
        if (int_len > 19) return CAUSA_A108;
        for (d = int_start; d < int_start + int_len; d++) magnitude = magnitude * 10 + (uint64_t)(*d - '0');
        if (magnitude > (uint64_t)INT64_MAX) return CAUSA_A108;
        *type = CAUSA_TYPE_INT;
        out->i = negative ? -(int64_t)magnitude : (int64_t)magnitude;
        return CAUSA_OK;
    } else {
        /* digits without a decimal point, so strtod cannot depend on the locale */
        char *buf = (char *)malloc(int_len + frac_len + 16);
        double v;
        long scale;
        if (!buf) {
            fprintf(stderr, "%s: internal error: out of memory\n",
                    CAUSA_PROGRAM.source_file ? CAUSA_PROGRAM.source_file : "<unknown>");
            exit(2);
        }
        scale = (exp_negative ? -(long)exponent : (long)exponent) - (long)frac_len;
        memcpy(buf, int_start, int_len);
        memcpy(buf + int_len, frac_start, frac_len);
        sprintf(buf + int_len + frac_len, "e%ld", scale);
        v = strtod(buf, NULL); /* correctly rounded, like the compiler's float() */
        free(buf);
        if (isinf(v)) return CAUSA_A109;
        *type = CAUSA_TYPE_FLOAT;
        out->f = negative ? -v : v;
        return CAUSA_OK;
    }
}

static inline const char *causa_type_name(int type)
{
    return type == CAUSA_TYPE_INT ? "int" : type == CAUSA_TYPE_FLOAT ? "float" : "bool";
}

/* Validate every launch argument against the program's inputs before any
   statement runs; the first invalid argument (in argument order) is reported
   and the program exits with status 3 having produced no output. */
static inline void causa_configure(int argc, char **argv)
{
    causa_launch_state *s = causa_launch();
    size_t n = CAUSA_PROGRAM.binding_count > 0 ? (size_t)CAUSA_PROGRAM.binding_count : 1;
    causa_value *values;
    unsigned char *set;
    int i;
    if (argc <= 1) return; /* no arguments: source defaults, unchanged behavior */
    values = (causa_value *)calloc(n, sizeof *values);
    set = (unsigned char *)calloc(n, 1);
    if (!values || !set) {
        fprintf(stderr, "%s: internal error: out of memory\n",
                CAUSA_PROGRAM.source_file ? CAUSA_PROGRAM.source_file : "<unknown>");
        exit(2);
    }
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i], *eq, *value;
        int b, binding = -1, literal_type = CAUSA_TYPE_INT, code;
        size_t name_len;
        causa_value v;
        v.i = 0; /* causa_argument_error never returns, but C99 cannot say so */
        if (strcmp(arg, "--set") != 0)
            causa_argument_error(CAUSA_A101, "unknown argument '%s' (expected --set NAME=VALUE)", arg);
        if (i + 1 >= argc) causa_argument_error(CAUSA_A102, "--set needs NAME=VALUE");
        arg = argv[++i];
        eq = strchr(arg, '=');
        if (!eq || eq == arg || eq[1] == '\0')
            causa_argument_error(CAUSA_A102, "expected NAME=VALUE after --set, found '%s'", arg);
        name_len = (size_t)(eq - arg);
        value = eq + 1;
        for (b = 0; b < CAUSA_PROGRAM.binding_count; b++) {
            const char *name = CAUSA_PROGRAM.bindings[b].name;
            if (name && strlen(name) == name_len && strncmp(name, arg, name_len) == 0) { binding = b; break; }
        }
        if (binding < 0) causa_argument_error(CAUSA_A103, "'%.*s' is not a declared input", (int)name_len, arg);
        if (CAUSA_PROGRAM.bindings[binding].kind != CAUSA_KIND_INPUT)
            causa_argument_error(CAUSA_A104, "'%.*s' is a let binding; only inputs can be set", (int)name_len, arg);
        if (set[binding]) causa_argument_error(CAUSA_A105, "input '%.*s' is set more than once", (int)name_len, arg);
        code = causa_parse_literal(value, &literal_type, &v);
        if (code == CAUSA_A106)
            causa_argument_error(code, "'%s' is not a valid value for input '%.*s'", value, (int)name_len, arg);
        if (code == CAUSA_A108)
            causa_argument_error(code, "integer value '%s' for input '%.*s' exceeds 9223372036854775807", value,
                                 (int)name_len, arg);
        if (code == CAUSA_A109)
            causa_argument_error(code, "float value '%s' for input '%.*s' is too large", value, (int)name_len, arg);
        if (literal_type == CAUSA_TYPE_INT && CAUSA_PROGRAM.bindings[binding].type == CAUSA_TYPE_FLOAT) {
            v.f = (double)v.i; /* the int-to-float promotion of a whatif override (D15) */
            literal_type = CAUSA_TYPE_FLOAT;
        }
        if (literal_type != CAUSA_PROGRAM.bindings[binding].type)
            causa_argument_error(CAUSA_A107, "cannot set %s input '%.*s' to the %s value '%s'",
                                 causa_type_name(CAUSA_PROGRAM.bindings[binding].type), (int)name_len, arg,
                                 causa_type_name(literal_type), value);
        values[binding] = v;
        set[binding] = 1;
    }
    s->values = values; /* applied all at once, only after every argument is valid */
    s->set = set;
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
/* One override of a whatif: an input binding and its value, which already has
   the input's type (promoted by the compiler if needed). */
typedef struct {
    int input;
    causa_value value;
} causa_override;

/* `overrides` holds override_count >= 1 distinct inputs in statement order;
   target is CAUSA_NO_TARGET for the full form. */
void causa_whatif(const causa_value *env, const causa_override *overrides, int override_count,
                  int target_binding, int visible);
/* Exits with status 1 and a diagnostic if !ok. */
void causa_assert(const causa_value *env, int assert_index, bool ok);

#endif /* CAUSA_RUNTIME_H */
