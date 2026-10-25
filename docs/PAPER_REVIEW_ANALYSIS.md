# Paper Review Analysis

## Paper

**Title:** A Comparative Analysis of Lightweight Transformer-Based Models Applied to Image Super-Resolution

## Overall Assessment

The paper has a solid structure and a clear comparative objective. Its strongest aspects are the organization of the manuscript, the methodological background, and the conclusion, which is aligned with the reported results. The main weaknesses are in the clarity of the experimental protocol, the quality of the English in several passages, and the positioning of the work within the most relevant lightweight and efficient super-resolution literature.

## Strengths

- The paper is well structured and easy to follow.
- The background and motivation for lightweight single-image super-resolution are relevant.
- The methodology section appears conceptually organized around a comparative evaluation.
- The conclusion is coherent with the reported findings.
- The combination of quantitative and qualitative analysis is appropriate for this topic.

## Main Weaknesses

### 1. English Needs Revision

The manuscript is understandable, but the English is not yet publication-ready. Several passages read as direct translation or contain awkward academic phrasing.

Examples of recurring issues:

- Inconsistent language presentation, such as the presence of "Resumo" in a paper otherwise written in English.
- Awkward expressions such as "technical tie" and repetitive constructions like "perceptible to the naked eye."
- Sentences that are too long and syntactically overloaded.
- Occasional misuse of evaluation terminology, especially "validated on" where "evaluated on" is probably the correct wording.
- Some claims are stronger than the evidence presented.

Recommended action:

- Perform a full English revision focused on concision, article usage, punctuation, and standard academic phrasing.
- Standardize all front matter, section titles, figure captions, and terminology in English.

### 2. Validation and Training Protocol Are Not Clear Enough

This is the main technical weakness of the paper.

The manuscript states that the models were trained on DIV2K and validated on Set5, Set14, B100, Urban100, and Manga109. This wording is problematic because these datasets are usually presented as benchmark test sets in the super-resolution literature, not as a validation protocol. As written, the experimental design is unclear and difficult to reproduce.

The paper should state explicitly:

- Whether the models were trained from scratch, fine-tuned, or evaluated from official pretrained weights.
- What the actual train, validation, and test split was.
- How the lightweight variants were defined relative to the original architectures.
- The optimizer, learning rate, scheduler, batch size, patch size, number of epochs or iterations, and loss function.
- The data augmentation strategy, if any.
- The hardware and software environment used for training and inference.
- How inference time and VRAM usage were measured.
- Whether PSNR and SSIM were computed on RGB or Y channel, and whether border cropping followed standard benchmark protocol.
- How model checkpoints were selected.
- Whether random seeds or repeated runs were used.

Why this matters:

- Without these details, the comparison is hard to reproduce.
- It is difficult to judge whether the comparison between the three models is fair.
- The practical recommendation in favor of SSIU becomes less convincing if latency and memory measurements are not fully specified.

### 3. Reference Coverage Can Be Improved

The bibliography is relevant, but it still misses some important literature in lightweight and efficient super-resolution. This is especially important because the paper positions itself as a comparison of compact SR models for resource-limited settings.

## Most Important Missing References

The two most useful references to add are:

1. **CARN: Cascading Residual Network for Efficient Super-Resolution**  
   Ahn, N., Kang, B., and Sohn, K.-A. (2018). *Fast, Accurate, and Lightweight Super-Resolution with Cascading Residual Network*. ECCV.

   Why it matters: CARN is a classic lightweight SR baseline and is highly relevant for any discussion of efficiency-quality trade-offs.

2. **ESRT: Efficient Transformer for Single Image Super-Resolution**  
   Lu, Z., Zhang, H., Yang, J., and Huang, Y. (2022). *Efficient Transformer for Single Image Super-Resolution*.

   Why it matters: This is the most relevant transformer-based comparison point for a paper focused on lightweight transformer SR models.

These two references would better situate the work in the current literature without overloading the bibliography.

## Additional Technical Comments

- The term "technical tie" should be replaced by a more precise expression such as "comparable performance" unless the paper defines a threshold for practical equivalence.
- The qualitative analysis would be stronger if the authors explained how the visual crops were selected.
- If SSIU is recommended for hardware-constrained scenarios, the paper should clearly define the evaluation conditions for runtime and memory measurements.
- The discussion of MambaIRv2-light should separate architecture-level interpretation from the specific experimental setup, since underperformance in this study does not necessarily generalize.

## Recommendation for Revision

The paper has a solid basis and can become a stronger contribution with targeted revisions. The priority order should be:

1. Clarify the experimental protocol in a reproducible way.
2. Revise the English throughout the manuscript.
3. Add the two missing lightweight SR references above.
4. Rephrase claims that currently sound stronger than the evidence supports.

## Short Reviewer-Style Summary

This is a well-structured paper with a relevant topic and a coherent conclusion. However, the manuscript still needs improvement in English and stronger clarity in the validation and training protocol. The main missing literature gap is the lack of lightweight SR baselines and an efficient transformer reference, especially CARN and ESRT.