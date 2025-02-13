# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [v4.1.0] - 2025-02-19
- [pull/147](https://github.com/MAAP-Project/maap-api-nasa/pull/147) - Removed the need for tracking environments.json

## [v4.1.0] - 2024-09-10
- [pull/131](https://github.com/MAAP-Project/maap-api-nasa/pull/131) - Added query params to job list endpoint 
- [pull/135](https://github.com/MAAP-Project/maap-api-nasa/pull/135) - User secret management 
- [pull/137](https://github.com/MAAP-Project/maap-api-nasa/pull/137) - Organizations & job queues management
- [pull/136](https://github.com/MAAP-Project/maap-api-nasa/pull/136) - Add support for DPS sandbox queue
- [pull/132](https://github.com/MAAP-Project/maap-api-nasa/pull/132) - Remove {username} param from DPS job list endpoint 

## [v4.0.0] - 2024-06-26
- [issues/111](https://github.com/MAAP-Project/maap-api-nasa/issues/111) - Implement github actions CICD and convert to poetry based build
- [pull/110](https://github.com/MAAP-Project/maap-api-nasa/pull/110) - Remove postgres from docker-compose
- [issues/112](https://github.com/MAAP-Project/maap-api-nasa/issues/112) - Update settings.py to load settings from OS Environment
- [pull/116](https://github.com/MAAP-Project/maap-api-nasa/pull/116) & [issues/909](https://github.com/MAAP-Project/Community/issues/909) - Add /config endpoint that can be used to configure maap-py
- [pull/122](https://github.com/MAAP-Project/maap-api-nasa/pull/122) - Bump lightweight jobs from v0.0.5 to v1.2.2


[unreleased]: https://github.com/MAAP-Project/maap-api-nasa/v4.0.0...HEAD
[v4.1.0]: https://github.com/MAAP-Project/maap-api-nasa/compare/v4.0.0...v4.1.0
[v4.0.0]: https://github.com/MAAP-Project/maap-api-nasa/compare/v3.1.5...v4.0.0
