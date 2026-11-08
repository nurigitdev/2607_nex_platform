# P5-CA01A v1.1 Package

Copy the contents under:

```text
docs/transition/P5/
```

into the repository's `docs/transition/P5/` directory.

Recommended handling:

1. move old v1.0 P5 docs/contracts to `docs/transition/P5/HISTORY/` or retain through Git history;
2. keep `P5_CA01_Frozen_Source_Manifest_v1.0.csv` unchanged;
3. add P5-CA01A closure;
4. add/replace v1.1 documents and schemas;
5. commit design baseline before P5-S1 source implementation.

The v1.1 package closes five items:

- UUID Runtime ExecutableStep vs deterministic E-key;
- bare SHA-256 vs `sha256:` semantic hash references;
- validation status → runtime mapping;
- null WRITE fields in P5 StepResult;
- atomic Prompt binding history + pointer update.
