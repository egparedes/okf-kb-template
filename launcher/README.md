# okf-kb

A global `kb` command for knowledge bases generated from
[okf-kb-template](https://github.com/egparedes/okf-kb-template). It finds the
knowledge base you mean and runs *that* knowledge base's own `kb` tool, so
each knowledge base keeps the tool version of its template release.

```sh
uv tool install "git+https://github.com/egparedes/okf-kb-template#subdirectory=launcher"
kb check                 # inside a knowledge base
kb -C work find --type Tool # a registered one, from anywhere
kb --list                # registered knowledge bases
```

See the [documentation](https://egparedes.github.io/okf-kb-template/how-to/install-the-cli-launcher/).
