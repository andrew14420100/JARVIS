# Third-party components and architectural references

## OpenJarvis

Repository: `open-jarvis/OpenJarvis`

JARVIS can optionally install and use OpenJarvis as a secondary cognitive/planning layer through `requirements-cognitive.txt` and `jarvis/brain/openjarvis_adapter.py`.

OpenJarvis is licensed under the Apache License 2.0. This project does not vendor the OpenJarvis source tree; it imports the separately installed package at runtime.

## isair/jarvis

Repository: `isair/jarvis`

The room-presence behavior in this project is independently implemented after studying the public behavior and architecture described by `isair/jarvis`: short rolling conversational context, activation by Jarvis, and local-first voice interaction.

No source code from `isair/jarvis` is vendored or copied into this repository. This matters because `isair/jarvis` uses a non-commercial license that requires derivative works containing its code to remain under the same non-commercial terms.

The local presence implementation in this project keeps recent audio only in an in-memory ring buffer. It transcribes that buffer only after Jarvis is invoked and does not persist the ambient audio to disk.
