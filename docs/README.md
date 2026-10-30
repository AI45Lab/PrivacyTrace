# Project website

The project page uses the original [Nerfies website template](https://github.com/nerfies/nerfies.github.io).
The title, authors, abstract, and figures follow the current PrivacyTrace paper.
Template, font, and icon notices are retained under `vendor/` and in the footer.

- Code: https://github.com/AI45Lab/PrivacyTrace
- Website: https://sowingg2333.github.io/PrivacyTrace-website/
- Hosting repository: https://github.com/SowingG2333/PrivacyTrace-website

## Preview

From the code repository root:

```bash
python3 -m http.server 8080
```

Open [the project page](http://localhost:8080/docs/).

## Deployment

The website source is retained in this `docs/` directory. Copy `index.html`,
`app.js`, `styles.css`, `site-config.js`, `.nojekyll`, `assets/`, and `vendor/`
to the hosting repository root. GitHub Pages publishes that repository's
`main` branch from `/`, with no build step.

`repository` in `site-config.js` points to the organization code repository.
The Paper button remains an arXiv placeholder until `paper` has a URL.
When publishing the paper, also update the arXiv badge and link in the root README.
