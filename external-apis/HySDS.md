# HySDS API
MAAP API uses the [HySDS API](https://ec2-54-86-171-31.compute-1.amazonaws.com/mozart/api/v0.1/doc/) to run queued batch jobs, and to catalog algorithm output.

## Required endpoints for job creation and monitoring
- [/job/submit](https://ec2-54-86-171-31.compute-1.amazonaws.com/mozart/api/v0.1/job/submit): submits a job to run in HySDS.
- [/job/info](https://ec2-54-86-171-31.compute-1.amazonaws.com/mozart/api/v0.1/job/info): get info on a submitted HySDS job.

## Additional considerations

Two possible approaches for defining jobs include, 1) the use of a generic HySDS job container that is designed to run any algorithm or analysis workload, or 2) the generation of separate job containers corresponding to each separate algorithm in the MAAP algorithm library.
 
### All-purpose HySDS job container approach

Using a generic HySDS job that is associated to *n* MAAP algorithms, the HySDS `job` endpoints would be utilized for invoking a single, all-purpose job. The parameters here would consist of variable size array that maps to the algorithm inputs. 

Using this approach, provenance data related to the job entry and submitter would be attached to the job via the `Tag` property. The job definition itself would be maintained in its own repo in the same GitLab project hosting the algorithm library repos.

### Single-purpose HySDS job container approach

A single-purpose approach would involve generating a separate HySDS job for each MAAP repo in the MAAP GitLab directory. In this scenario, the HySDS `/container/*` API would be required for auto-generating individual containers as new GitLab repos are created or existing repos are updated.



