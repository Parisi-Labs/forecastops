# ForecastOps Examples

Run these from the repository root after installing the package:

```bash
pip install -e ".[all]"
python examples/generic_dataframe.py
fops ui
```

## Notebook

[`quickstart.ipynb`](quickstart.ipynb) walks the full loop interactively —
capture → metrics → validation → benchmark → diff → report/UI — and is
committed with its outputs so it renders on GitHub:

```bash
pip install jupyter
jupyter lab examples/quickstart.ipynb
```

