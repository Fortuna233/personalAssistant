# Repository Guidelines

## Project Structure & Module Organization

This repository is currently an empty project scaffold. No source code, tests, assets, or package configuration have been added. As the project grows, group files by responsibility and document the resulting layout in `README.md`.

Suggested starting directories are `src/` for application code, `tests/` for automated tests, and `assets/` for static resources. Create these only when needed. Keep configuration files at the repository root and place reusable scripts in `scripts/`.

## Build, Test, and Development Commands

No build, test, or local development commands are configured yet. When introducing a language or framework, provide reproducible setup instructions and document the exact commands in `README.md`.

Expose common tasks through the chosen package manager or build tool. Explain installation, local execution, testing, and production builds. Do not document commands such as `npm test` or `make build` until their configuration exists.

## Coding Style & Naming Conventions

Follow the idiomatic conventions of the language selected for the project. Configure a formatter and linter when adding the first source files, and commit their configuration.

Use descriptive names, consistent indentation, and small modules with clear responsibilities. Match existing naming patterns when extending a module. Avoid mixing unrelated formatting changes with functional changes.

## Testing Guidelines

No testing framework or coverage threshold is established. Add an appropriate framework alongside the first testable functionality. Keep tests deterministic and independent of private credentials or live services.

Use descriptive test names that identify the behavior under test, and follow the framework's file naming convention. Include regression tests for bug fixes and document how contributors can run the suite.

## Commit & Pull Request Guidelines

No Git history is available to establish a commit convention. Use concise, imperative commit subjects, such as `Add configuration loader`, and keep each commit focused.

Pull requests should describe the change, its purpose, and validation performed. Link relevant issues when available; include screenshots for visible UI changes. State any setup changes or remaining limitations.

## Security & Configuration

Never commit credentials, tokens, or private data. Supply placeholder values in example configuration files and document required environment variables. Ignore local secrets and generated artifacts when adding version control configuration.
