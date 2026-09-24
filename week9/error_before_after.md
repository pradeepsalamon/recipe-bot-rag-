### Before (Old Docstring and Error)
**Model Tool Call:**
`{"tool": "substitute_ingredient", "arguments": {"ingredient": "creme fraiche lite", "reason_type": "DIET", "diet": "VEGAN"}}`

**Tool Result:**
`{"ingredient": "creme fraiche lite", "constraint_type": "DIET", "constraint": "VEGAN", "substitute": null, "note": "No known substitution for 'creme fraiche lite' under constraint VEGAN. The ingredient may already be compatible, or manual review is needed.", "needs_further_check": true}`

**Model Behavior:**
The model gets confused because it receives a definitive "no known substitution" and might invent a substitution, confidently stating that the user should just use water, or it might skip the substitution entirely.

---

### After (New Docstring and Recoverable Error)
**Model Tool Call:**
`{"tool": "do_substitute_ingredient", "arguments": {"ingredient": "creme fraiche lite", "reason_type": "DIET", "diet": "VEGAN"}}`

**Tool Result:**
`{"ingredient": "creme fraiche lite", "constraint_type": "DIET", "constraint": "VEGAN", "substitute": null, "note": "No exact match for 'creme fraiche lite'. Try a simpler term (e.g. 'flour' instead of 'wheat flour') or verify it needs substitution.", "needs_further_check": true}`

**Model Behavior:**
Due to the new prompt docstring ("If you get a 'No known substitution' error, try providing just the base ingredient name...") and the recoverable error message, the model realizes its mistake and immediately retries with the simpler term:
`{"tool": "do_substitute_ingredient", "arguments": {"ingredient": "cream", "reason_type": "DIET", "diet": "VEGAN"}}`

**Subsequent Tool Result:**
`{"ingredient": "cream", "constraint_type": "DIET", "constraint": "VEGAN", "substitute": "coconut cream", "note": "Use coconut cream as a 1:1 replacement.", "needs_further_check": false}`

**Result:** The model successfully finds the vegan substitute instead of failing.
