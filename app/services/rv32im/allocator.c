/* Single-threaded bounded allocator for the educational RV32IM simulator.
 * 4 KiB arena, 16-byte alignment, first fit, splitting and coalescing.
 * Zero-size requests return NULL; realloc(p, 0) releases p and returns NULL.
 * Invalid/double frees and writes outside allocations remain invalid C usage.
 */
#include "include/stdlib.h"

#define ARENA_SIZE 4096u
#define ALIGNMENT 16u
typedef union Block {
    struct { size_t size; size_t used; } info;
    unsigned char padding[ALIGNMENT];
} Block;

#ifdef ARCHREACTOR_HOST_TEST
static unsigned char arena[ARENA_SIZE] __attribute__((aligned(16)));
#else
/* CORE models sparse virtual RAM here. An absolute linker symbol avoids an
 * unsupported ELF section and avoids serializing unused heap words each cycle. */
extern unsigned char __archreactor_heap_start[];
#define arena __archreactor_heap_start
#endif
static int initialized;

static Block *next_block(Block *block) {
    unsigned char *next = (unsigned char *)(block + 1) + block->info.size;
    return next < arena + ARENA_SIZE ? (Block *)next : NULL;
}

void *malloc(size_t size) {
    if (!size || size > ARENA_SIZE - sizeof(Block)) return NULL;
    size = (size + ALIGNMENT - 1) & ~(size_t)(ALIGNMENT - 1);
    if (!initialized) {
        Block *first = (Block *)arena;
        first->info.size = ARENA_SIZE - sizeof(Block);
        first->info.used = 0;
        initialized = 1;
    }
    for (Block *block = (Block *)arena; block; block = next_block(block)) {
        if (block->info.used || block->info.size < size) continue;
        if (block->info.size >= size + sizeof(Block) + ALIGNMENT) {
            Block *rest = (Block *)((unsigned char *)(block + 1) + size);
            rest->info.size = block->info.size - size - sizeof(Block);
            rest->info.used = 0;
            block->info.size = size;
        }
        block->info.used = 1;
        return block + 1;
    }
    return NULL;
}

void free(void *ptr) {
    if (!ptr) return;
    Block *released = (Block *)ptr - 1;
    released->info.used = 0;
    for (Block *block = (Block *)arena; block;) {
        Block *next = next_block(block);
        if (!block->info.used && next && !next->info.used) {
            block->info.size += sizeof(Block) + next->info.size;
        } else {
            block = next;
        }
    }
}

void *calloc(size_t count, size_t size) {
    if (!count || !size || count > (ARENA_SIZE - sizeof(Block)) / size) return NULL;
    size_t total = count * size;
    unsigned char *ptr = malloc(total);
    if (ptr) for (size_t i = 0; i < total; i++) ptr[i] = 0;
    return ptr;
}

void *realloc(void *ptr, size_t size) {
    if (!ptr) return malloc(size);
    if (!size) { free(ptr); return NULL; }
    Block *block = (Block *)ptr - 1;
    if (size <= block->info.size) return ptr;
    unsigned char *replacement = malloc(size);
    if (!replacement) return NULL; /* The original allocation stays valid. */
    for (size_t i = 0; i < block->info.size; i++) replacement[i] = ((unsigned char *)ptr)[i];
    free(ptr);
    return replacement;
}
