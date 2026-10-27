# Quick Reference Card

> Historical reference: bundled B0 Bicep files and automatic baseline validation
> were removed on 2026-10-25. Commands below that use `templates/bicep` are obsolete.
> Use the [current setup and artifact workflow](README.md) instead.

**Workspace**: `C:\Users\Andrey Victor Justo\workspace\network-simulation`  
**Print-friendly**: ✅ Save as PDF for quick reference

---

## 🚀 Quick Commands

### Run the POC
```bash
cd "c:\Users\Andrey Victor Justo\workspace\network-simulation"
python main.py
```

### View Results
```bash
Get-ChildItem reports/*.json
cat reports/stage3_analysis.json
```

### View Scenarios
```bash
python -c "from scenarios.scenario_specs import list_all_scenarios; print(list_all_scenarios())"
```

### Validate a Template
```bash
python -c "
from validation.checkov_validator import CheckovValidator
v = CheckovValidator()
r = v.validate_template('templates/bicep/net-01-basic-vnet.bicep', 'NET-01')
print(f'Acceptance: {r.acceptance_rate}%')
"
```

---

## 📁 Important Files

### Documentation
| File | Purpose |
|---------|-----------|
| [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) | One page (managers) |
| [docs/POC_GUIDE.md](docs/POC_GUIDE.md) | Usage guide |
| [docs/POC_RESULTS.md](docs/POC_RESULTS.md) | Pilot results |
| [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md) | Roadmap Phase 1-5 |
| [docs/INTEGRATION_MAP.md](docs/INTEGRATION_MAP.md) | Main project integration |

### Main Code
| File | Lines | Description |
|---------|--------|-----------|
| [main.py](../main.py) | 250 | Three-stage orchestrator |
| [configuration package](../src/network_simulation/configuration/__init__.py) | Modular | Settings |

### Modules
| File | Lines | Classes |
|---------|--------|---------|
| [scenarios/scenario_specs.py](../../scenarios/scenario_specs.py) | 450 | 10 scenarios |
| [validation/checkov_validator.py](../../validation/checkov_validator.py) | 300 | CheckovValidator |
| [experiments/experiment_runner.py](../../experiments/experiment_runner.py) | 450 | ExperimentRunner |
| [evaluation/metric_analyzer.py](../../evaluation/metric_analyzer.py) | 350 | MetricAnalyzer |

### Templates
| File | Scenario | Status |
|---------|---------|--------|
| [net-01-basic-vnet.bicep](../../templates/bicep/net-01-basic-vnet.bicep) | NET-01 | ✅ |
| [net-02-segmentation.bicep](../../templates/bicep/net-02-segmentation.bicep) | NET-02 | ✅ |
| [net-03-nsg-security.bicep](../../templates/bicep/net-03-nsg-security.bicep) | NET-03 | ✅ |

---

## 📊 Data Structure

### Scenario (scenario_specs.py)
```python
{
  "scenario_id": "NET-01",
  "name": "Basic Virtual Network",
  "objective": "...",
  "acceptance_criteria": [8-15 strings],
  "connectivity_requirements": [strings],
  "security_requirements": [strings],
  "architectural_requirements": [strings]
}
```

### Experiment (experiment_runner.py)
```python
IterationResult:
  - iteration_num: int
  - condition: "B1" | "T1"
  - template_content: str
  - validation_passed: bool
  - security_violations: int
  - checkov_score: float
  - execution_time_seconds: float

ScenarioExperimentResult:
  - scenario_id: str
  - b1_iterations: [IterationResult]
  - t1_iterations: [IterationResult]
  - b1_acceptance_rate: float
  - t1_acceptance_rate: float
  - improvement_acceptance_rate: float
  - improvement_violations: float
```

### Metrics (metric_analyzer.py)
```python
NetworkScenarioMetrics:
  - violation_rate: float (%)
  - acceptance_rate: float (%)
  - connectivity_correctness: float (%)
  - iterations_to_acceptance: int

B1 vs T1 Comparison:
  - violation_rate_delta: float
  - acceptance_rate_delta: float
  - iterations_delta: int
```

---

## 🧪 The 3 POC Stages

### Stage 1: Baseline Validation
```
Input: Bicep templates (B0)
Process: Checkov scan
Output: stage1_baseline_validation.json
└── acceptance_rate, violations per template
```

### Stage 2: Experiment
```
Input: Configuration (num scenarios, max iterations)
Process: Simulates B1 vs T1 per scenario
Output: experiment_*.json
└── b1_iterations[], t1_iterations[], metrics
```

### Stage 3: Analysis
```
Input: Stage 2 data
Process: Compares B1 vs T1, tests H1/H2/H3
Output: stage3_analysis.json
└── hypothesis_support, deltas, aggregation
```

---

## 🔢 Expected Statistics

### After `python main.py` (Pilot)
```
Total Scenarios: 3
Total Runs: 6 (3 scenarios × 2 conditions)

NET-01:
  B1 Iterations: 3 | T1 Iterations: 1
  B1 Violations: 1.7 | T1 Violations: 0.0
  Improvement: 50pp violation reduction

NET-02:
  B1 Iterations: 4 | T1 Iterations: 2
  B1 Violations: 2.5 | T1 Violations: 1.0
  Improvement: 80pp violation reduction

NET-03:
  B1 Iterations: 5 | T1 Iterations: 1
  B1 Violations: 3.2 | T1 Violations: 2.0
  Improvement: 140pp violation reduction

HYPOTHESES:
  H1 (B1 > T1 violations): 100% supported ✅
  H2 (T1 higher acceptance): Requires real data ⚠️
  H3 (T1 more efficient): 2.7x fewer iterations ✅
```

---

## 🎯 Immediate Next Steps

### This Week
- [ ] Choose an LLM (OpenAI, Anthropic, Azure)
- [ ] Prepare API keys

### Next Week (Phase 1)
- [ ] Install Checkov
- [ ] Implement NET-04 through NET-10 templates
- [ ] OPA/Rego policies
- [ ] Refine prompts

### Weeks 3-5 (Phase 2)
- [ ] LLM integration
- [ ] llm_generator.py
- [ ] Experiment with real data

### Weeks 6-12 (Phases 3-5)
- [ ] Pilot experiment
- [ ] Main experiment (10 scenarios)
- [ ] Main project integration

---

## 🐛 Troubleshooting

### Error: "Checkov not found"
```
Solution: pip install checkov==3.2.0
```

### Error: "Template not found"
```
Solution: Templates must be in templates/bicep/*.bicep
```

### POC does not generate reports
```
Solution: Check that the reports/ directory exists
          Check write permissions
```

### Zero-valued metrics
```
Solution: Stage 2 simulation = mock data
          Use real data: Phase 2 LLM integration
```

---

## 🔗 Reference Links

### Current Workspace
- `C:\Users\Andrey Victor Justo\workspace\network-simulation`

### Main Project
- `C:\Users\Andrey Victor Justo\workspace\coding-tool-reasoning`

### Documentation
- [Complete Index](INDEX.md)
- [Detailed Roadmap](NEXT_STEPS.md)
- [Integration](INTEGRATION_MAP.md)

---

## 💡 Quick Tips

### To Understand a Scenario
```bash
python -c "
from scenarios.scenario_specs import get_scenario_spec
spec = get_scenario_spec('NET-03')
print('Acceptance Criteria:')
for i, c in enumerate(spec.acceptance_criteria, 1):
  print(f'  {i}. {c}')
"
```

### To View Template Violations
```bash
python -c "
from validation.checkov_validator import CheckovValidator
v = CheckovValidator()
r = v.validate_template('templates/bicep/net-03-nsg-security.bicep', 'NET-03')
print('Security Violations:', r.security_violations)
print('Policy Violations:', r.policy_violations)
"
```

### To Modify Configuration
```python
# src/network_simulation/configuration/
ExperimentConfig:
  - phase: "pilot" | "main"
  - scenarios: ["NET-01", "NET-02", ...]
  - max_iterations: 10

LLMConfig:
  - provider: "openai" | "anthropic" | "azure"
  - model_name: "gpt-4"
  - temperature: 0.3  # For determinism
```

---

## 📱 Useful Commands

```bash
# List templates
Get-ChildItem templates/bicep/*.bicep

# Count lines of code
Get-Content main.py, src/network_simulation/configuration/*.py | Measure-Object -Line

# View report sizes
Get-ChildItem reports/*.json | Format-Table Name, @{Name="Size(KB)"; Expression={[math]::Round($_.Length/1KB, 2)}}

# Extract statistics from JSON
Get-Content reports/stage3_analysis.json | ConvertFrom-Json | Select-Object -ExpandProperty hypothesis_support

# Find a scenario in the documentation
Get-ChildItem docs/ | Select-String -Pattern "NET-05"
```

---

## 🏆 Verification Checklist

### After Cloning/Setup
- [ ] Python 3.10+ installed
- [ ] `cd network-simulation`
- [ ] `requirements.txt` available
- [ ] `main.py` present

### Before Running
- [ ] Checkov installed (next iteration)
- [ ] LLM configuration prepared (next iteration)
- [ ] `reports/` directory ready
- [ ] Write permissions OK

### After `python main.py`
- [ ] stage1_baseline_validation.json generated
- [ ] experiment_*.json generated
- [ ] stage3_analysis.json generated
- [ ] No fatal errors in the logs

---

## 📞 Contacts

| Role | Owner |
|-------|------------|
| POC Architecture | Andrey Victor Justo |
| Research | Andrey Victor Justo |
| LLM Integration | TBD |
| DevOps/Infra | TBD |

---

**Last Updated**: 2026-09-05  
**Version**: 0.1.0  
**Printed**: [Date]
