.section .text.start
.globl _start
_start:
    call main
    li a7, 10
    ecall
1:  j 1b
