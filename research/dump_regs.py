import re

t = open('research/courbet.dts', encoding='utf-8', errors='replace').read()
for m in re.finditer(r'regulator-(pm6150l-l\d+)\s*\{(.*?)\n\s*\};', t, re.S):
    name = m.group(1)
    body = m.group(2)

    def g(k):
        mm = re.search(k + r'\s*=\s*<([^>]+)>', body)
        return mm.group(1).strip() if mm else '-'

    print(f"{name:18} init={g('qcom,init-voltage'):>10} min={g('regulator-min-microvolt'):>10} "
          f"max={g('regulator-max-microvolt'):>10} mode={g('qcom,init-mode')}")
