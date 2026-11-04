# xml-processes

Boomi process exports that are going to be deployed. Any pull request that adds or
changes an `.xml` file here runs the **XML Validation** workflow, which checks each
changed file against the Factory Safety Standards in
[`validation/factory_standards.toml`](../validation/factory_standards.toml).
