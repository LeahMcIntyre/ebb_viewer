# Pipeline Flow — Slide

Simple flowchart for a presentation. The key idea: a spindle *rerun*
is just re-running sleep staging with a different channel combination.

## Mermaid

```mermaid
flowchart LR
    A[Raw EEG] --> B[Preprocess]
    B --> C["Sleep staging<br/><i>via spindle detection</i><br/>channels: LFC + RSC"]
    C --> D{Sleep QC}
    D -- Pass --> E["Preprocessed EDF<br/>+ Sleep Stages<br/><b>Ready for PSD Computation</b>"]
    D -- Bad staging --> F["Rerun<br/><b>different channels</b><br/>e.g. LSC + RSC"]
    F --> C

    classDef rerun fill:#cfe2f3,stroke:#3a6ea5,color:#111;
    classDef ready fill:#d9ead3,stroke:#3a7d3a,color:#111;
    class F rerun;
    class E ready;
```

## ASCII

```
                                              +----------------------+
                                              |   Rerun              |
                                              | (different channels) |
                                              |   e.g. LSC + RSC     |
                                              +----------+-----------+
                                                         ^
                                                         |  Bad staging
                                                         |
+---------+   +------------+   +------------------+   +--+-------+   +--------------------+
| Raw EEG |-->| Preprocess |-->|  Sleep staging   |-->| Sleep QC |-->| Preprocessed EDF   |
+---------+   +------------+   | via spindle det. |   +----------+   | + Sleep Stages     |
                               | ch: LFC + RSC    |       Pass       | Ready for PSD comp.|
                               +------------------+                  +--------------------+
```
