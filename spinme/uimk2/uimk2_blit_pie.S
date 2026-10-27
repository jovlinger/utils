/* ESP32-S3 PIE helpers: 128-bit (16-byte) load/store for pack66 spans.
 * Windowed ABI. Do not clobber Q regs from C; these functions own q0.
 *
 * a2 = memory pointer (16-byte aligned)
 * a3 = 16-byte aligned scratch
 */
    .text
    .align 4

    .global uimk2_pie_load16
    .type uimk2_pie_load16, @function
uimk2_pie_load16:
    entry   a1, 32
    ee.vld.128.ip q0, a2, 0
    ee.vst.128.ip q0, a3, 0
    retw.n
    .size uimk2_pie_load16, .-uimk2_pie_load16

    .align 4
    .global uimk2_pie_store16
    .type uimk2_pie_store16, @function
uimk2_pie_store16:
    entry   a1, 32
    ee.vld.128.ip q0, a3, 0
    ee.vst.128.ip q0, a2, 0
    retw.n
    .size uimk2_pie_store16, .-uimk2_pie_store16
