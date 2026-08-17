# heypeg — per-block “quality” for DCT/JPEG-style compression

This directory is a sketch space for experiments around **spatially varying effective quantization** of 8×8 DCT blocks—similar in spirit to using one global JPEG quality knob, but with a **per-block** (or per-region) notion of how hard to quantize.

## 1. The toy model

JPEG-like pipelines do three memorable things to each 8×8 block (per color component):

1. **Forward DCT** — transform spatial samples to frequency coefficients.
2. **Quantization** — divide by a quantization table and round to integers (this is where “quality” lives).
3. **Entropy coding** — zigzag order, DC prediction, run-length + Huffman (baseline) or arithmetic coding (less common in the wild).

Today, “quality 85” usually means: pick one luminance and one chrominance quantization table (or derive them from a single scalar), then apply that same table to **every** block of that component.

**heypeg idea:** attach a **quality map** over the block grid. Example: given a mask (“person”, “face”, “background”), use effective qualities like 95 for the person, 100 for the face, and 25 for the rest. The map is keyed by **block coordinates** \((b_x, b_y)\)—i.e. which 8×8 block in the raster—not per pixel.

### Would the resulting JPEG be conformant?

**It depends what you change.**

| Approach | Conformant baseline JPEG? | Notes |
|----------|---------------------------|--------|
| Different **quantization table index / matrix per 8×8 block** for the *same* component in one baseline sequential scan | **No** | Baseline SOF0 ties one quantization table destination (`Tq`) per component for the frame; decoders expect a consistent dequantization model per component. |
| Custom **per-block scaling of DCT coefficients (or pixels) before** a **single** standard quantization table and normal encode | **Yes** | The bitstream is ordinary JPEG; any compliant decoder reconstructs what the spec promises. You only changed encoder-side math. |
| Encode **separate** JPEGs (different qualities) and stitch tiles in the application | **Yes** (each file) | Not one JPEG image; composition is outside the single-stream model. |
| Proprietary / research extensions | Varies | Not “baseline JPEG” interchangeability. |

So: **literal** “this block uses matrix A, that block uses matrix B” for one luminance channel in one baseline image is **not** how interchange JPEG is defined. **Effective** per-block quality **via one published Q-table and encoder-side weighting** **is** conformant—the decoder sees a normal DQT + scan.

### Sketch: conformant per-block effective quality

Intuition: you want block \(b\) to behave as if it used a **stronger or weaker** quantizer than the baseline table. With a **single** standard table `Q[k]` (zigzag index `k`), pick a per-block positive scale `s_b` (derived from your quality map). One simple pattern:

- Forward DCT → coefficients `Y[k]`.
- Apply `Y'[k] = Y[k] / s_b` (or multiply `Q` effectively by `s_b`).
- Quantize: `Z[k] = round(Y'[k] / Q[k])`.
- Dequantize at decoder: `Y_hat[k] = Z[k] * Q[k]` (unchanged decoder).

Larger `s_b` ⇒ smaller `Y'` ⇒ more zeros after quantize ⇒ **harsher** compression for that block. Map “user quality” 0–100 monotonically to `s_b` (implementation detail).

**Non-goals for this README:** optimal psychovisual scaling, chroma handling, subsampling interaction, and rate control—these matter for a real encoder.

## 2. Quality maps: arrays, masks, and distance fields

### 2.1 Block grid array

The minimal API shape:

```text
quality[block_y][block_x]  ->  quality in [0, 100] or arbitrary monotone label
```

Build `s_b = f(quality[b_y][b_x])` with a monotone `f`, then run the pipeline above.

### 2.2 Signed distance functions (SDFs)

Instead of painting blocks by hand, define a **scalar field** over the image (or over block centers):

- For each region (e.g. “face”), maintain an SDF: distance to the boundary (negative inside, positive outside, or the reverse—pick one convention and stick to it).
- Map distance to quality: e.g. **closer to the face boundary from the inside** → higher quality; **farther in the background** → lower quality.

```pseudo
// Block-center sampling (conceptual)
for each block (bx, by):
    (cx, cy) = center_pixel(bx, by)
    d = sdf_face.sample(cx, cy)   // signed distance; negative inside face

    // Example: inside face gets high quality, outside falls off with distance
    if d <= 0:
        q = lerp(95, 100, smoothstep(d_inner, 0, d))   // core vs edge of face
    else:
        q = lerp(95, 25, smoothstep(0, d_falloff, d))   // background decay

    s[by][bx] = quality_to_scale(q)
encode_jpeg_with_per_block_scale(image, s, base_quant_table)
```

This is **encoder-only** metadata: the SDF never ships in the JPEG; only the quantized coefficients do.

### 2.3 Does it “work”?

- **As a conformant JPEG:** Yes, if you implement per-block scaling **before** quantization with a **single** spec-legal table (and legal sampling/Huffman tables). Any decoder displays it.
- **As “true” per-block Q-matrices in one baseline stream:** No—not without leaving baseline interchange.
- **Quality / artifacts:** Block boundaries may show **grid effects** if adjacent blocks use very different scales (classic adaptive quantization issue). Overlapping windows, smoothing the scale field across blocks, or tiling strategies mitigate this in practice.

## 3. End-to-end pseudo code (conformant path)

```pseudo
function encode_heypeg_conformant(rgb_image, quality_map_blocks, base_quality_scalar):
    // 1. Build one legal JPEG luminance/chroma quantization tables from base_quality_scalar
    QY, QC = standard_tables_from_quality(base_quality_scalar)

    for each component C in {Y, Cb, Cr}:
        Q = (C == Y) ? QY : QC
        for each 8x8 block b in raster order for C:
            coeffs = forward_dct_8x8(block_samples(b))
            s = scale_from_quality(quality_map_blocks[b.y][b.x], C)
            // Stronger compression => larger s (example convention)
            coeffs_scaled = coeffs / s
            quantized[b] = round(coeffs_scaled / Q)
    write_baseline_jpeg_scan(quantized, QY, QC, huffman_tables, ...)

function decode_standard(jpeg_bytes):
    // Unchanged — any library
    return standard_jpeg_decode(jpeg_bytes)
```

`scale_from_quality` can differ per component (e.g. keep chroma more conservative) without breaking conformance.

## 4. Prior art and related ideas

- **JPEG (baseline):** Single Q-table (per component) per frame; the interchange constraint that motivates the conformant vs non-conformant distinction above.
- **JPEG 2000:** **ROI (region of interest)** scaling is part of the design—different progression / refinement for regions; a closer “standard” story for spatial priority than baseline JPEG.
- **Video codecs (H.26x, VP9, AV1):** **Per-macroblock or segment QP** is routine; conceptually similar to a block quality map, but the bitstream explicitly carries QP indices.
- **HEIC / HEVC still images:** Tile/CTU-level QP variation in the still-image profile—again, the standard encodes the variation.
- **Research / product “saliency-aware” or “semantic” JPEG:** Many papers and systems vary quantization by importance map or segmentation; often implemented as **preprocess + standard JPEG**, or as **non-JPEG** codecs. Search terms: *region adaptive JPEG*, *saliency based image compression*, *semantic image compression*.
- **Mosaic of JPEGs:** Classic pragmatic approach for radically different regions (each tile conformant; the mosaic is app-level).

---

**Summary:** Per-block **effective** quality maps pair naturally with **encoder-side DCT scaling** and a **single legal quantization table** → **conformant** JPEG. Per-block **different published Q-matrices** for the same component in one baseline sequential image → **not** standard baseline behavior. SDFs are a convenient way to generate smooth quality fields over the block grid without hand-painting every cell.
