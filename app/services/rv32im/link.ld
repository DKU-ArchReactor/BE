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
  /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
