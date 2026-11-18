# CertDesk project instructions

Build the certificate administration console with Flask, SQLite and Vue 3. One local service serves the English interface and API. Keep the README in English. Project discussions may use Chinese.

Centralize database connections, parameter binding and tenant scoping. Scope all reads and writes to the actor's tenant. Commit certificates, audit events and bulk operation results in one transaction with explicit rollback. A revoked certificate remains revoked during later bulk issuance.

Reserve at least ten minutes for live verification, including cross-tenant access, concurrent issuance and a list request during CSV export. Keep genuine interaction and tool evidence. Record defects and actual verification outcomes.

The candidate independently authors Section 6. AI work covers the application, verification and other submission documentation.
