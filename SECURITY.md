# Security Policy

## Supported Versions

This project is currently in active development. Security updates are provided for:

| Version/Branch | Supported |
| --- | --- |
| Latest release on the main branch | :white_check_mark: |
| Older tagged releases | :x: |
| Unreleased or local development builds | :x: |

## Reporting a Vulnerability

Please report security vulnerabilities privately through GitHub Security Advisories rather than opening a public issue.

When reporting, include:

- A clear description of the vulnerability
- Steps to reproduce it
- Potential impact and affected components
- Any suggested mitigation

Please do not share sensitive information publicly. Avoid posting credentials, tokens, or private data in issues or pull requests.

### What to expect

- We aim to acknowledge reports within 5 business days.
- We will assess the issue, reproduce it when possible, and determine the appropriate remediation.
- If the report is accepted, we will work on a fix and release it as soon as possible.
- If the report is declined, we will explain the reasoning clearly.

## Security Areas of Interest

Please pay special attention to:

- Docker and container configuration
- Secret handling and environment variables
- File upload and OCR processing workflows
- Authentication and access control for any exposed services
- Dependency vulnerabilities in Node.js, Python, and container images
