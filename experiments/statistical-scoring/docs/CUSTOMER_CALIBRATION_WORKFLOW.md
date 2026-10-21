# Customer Calibration Workflow Diagram

```mermaid
flowchart TB
    A["1. First experiment execution<br/>Run cases with the selected evaluators"]
    B["Raw score store<br/>Scores plus evaluator, rubric, judge,<br/>dataset, and run configuration"]
    C["Uncalibrated report<br/>Equal-weight composite<br/>Calibration status: uncalibrated"]

    A --> B
    B --> C

    subgraph OBS["2. Collect calibration observations"]
        D1["Replay evaluators<br/>on fixed outputs<br/><b>Estimates judge variation</b>"]
        D2["Produce multiple agent runs<br/>for the same cases<br/><b>Estimates agent-run variation</b>"]
        D3["Evaluate multiple cases<br/>in the dataset<br/><b>Estimates case variation</b>"]
    end

    B --> D1
    B --> D2
    B --> D3

    D1 --> E
    D2 --> E
    D3 --> E

    E["3. Calibration engine<br/>Build tidy table<br/>Estimate variance and reliability<br/>Compare candidate weighting rules<br/>Bootstrap uncertainty"]
    F["Versioned calibration profile<br/>Configuration plus learned weights,<br/>uncertainty, diagnostics, and profile version"]
    G["4. Apply consistently<br/>Recompute current and historical reports<br/>using the same profile"]

    E --> F
    F --> G

    H["5. New evidence arrives<br/>Add applicable observations and recalibrate<br/>using all accumulated evidence"]
    G --> H
    H --> D1
    H --> D2
    H --> D3

    I["Optional early-data behavior<br/>Blend equal and learned weights as<br/>calibration confidence increases"]
    E -. candidate behavior .-> I
    I -.-> F
```

## One-Sentence Interpretation

The first report uses an equal-weight fallback, while repeated evaluator and agent observations allow
the system to learn, version, and continuously improve an experiment-specific calibration profile
that can be applied consistently to both current and historical scores.

