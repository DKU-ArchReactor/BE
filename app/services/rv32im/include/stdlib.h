#ifndef ARCHREACTOR_STDLIB_H
#define ARCHREACTOR_STDLIB_H

/* The teaching runtime implements only these four allocation functions. */
typedef __SIZE_TYPE__ size_t;
#define NULL ((void *)0)
void *malloc(size_t size);
void *calloc(size_t count, size_t size);
void *realloc(void *ptr, size_t size);
void free(void *ptr);

#endif
