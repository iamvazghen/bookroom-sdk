name: PR template
description: ""
body:
  - type: markdown
    attributes:
      value: |
        ## Before you open

        - [ ] I read [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md)
        - [ ] I ran the suites that cover my change (they cost nothing — no credits needed)
        - [ ] **No credential and no book content is in this diff**

  - type: textarea
    id: what
    attributes:
      label: What this changes
      description: What does the code do differently after this pull request?
    validations:
      required: true

  - type: textarea
    id: why
    attributes:
      label: Why
      description: What breaks or is impossible without it? Link the issue if there is one.
    validations:
      required: true

  - type: textarea
    id: verification
    attributes:
      label: How you verified it
      description: >
        Name the suites you ran and their results. If you added a bug fix, say
        which check fails without your change.
      placeholder: "verify_sdk.py 68/68; added 'merge creates parent dirs' to verify_facade.py"
    validations:
      required: true

  - type: checkbox
    id: engine
    attributes:
      label: This change does not modify the vendored engine files
      description: >
        The 19 files in `python/bookroom_sdk/_engine/` are deliberately
        unmodified copies. If you had to change engine behaviour, explain why
        in the "What this changes" box above — ideally change the wrapper
        instead.
