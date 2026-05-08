---
description: Write a human steer message that the gpr loop will pick up next iteration.
---

Take the rest of the user's command line as the steer message. Run:

```bash
gpr steer "<message>"
```

If the user passed `--abort`, append `--abort`. Confirm the file was written and remind the user that the next `/gpr` iteration will read it first.
