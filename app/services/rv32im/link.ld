OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x10000;
  .text : { *(.text.start) *(.text .text.*) }
  . = ALIGN(4);
  .rodata : { *(.rodata .rodata.*) }
  . = ALIGN(4);
  .data : { *(.data .data.*) *(.sdata .sdata.*) }
  . = ALIGN(4);
  .bss : { *(.bss .bss.*) *(.sbss .sbss.*) *(COMMON) }
  ASSERT(. <= 0x10004000, "Program overlaps the simulator heap")
  __archreactor_heap_start = 0x10004000;
  __archreactor_heap_end = 0x10005000;
  /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
