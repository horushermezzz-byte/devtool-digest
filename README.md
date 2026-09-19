# DevTool Digest

Practical, hands-on comparisons and guides for AI coding tools, developer productivity software, and self-hosted alternatives.

Built with [Hugo](https://gohugo.io/) + [PaperMod](https://github.com/adityatelange/hugo-PaperMod), deployed to GitHub Pages via GitHub Actions.

## Local development

```sh
hugo server --buildDrafts
```

## Deployment

Pushing to `main` triggers `.github/workflows/hugo.yml`, which builds and deploys to GitHub Pages automatically. No manual deploy step needed.

## Adding a new post

```sh
hugo new content posts/my-new-post.md
```

Set `draft: false` in the front matter when ready to publish.
