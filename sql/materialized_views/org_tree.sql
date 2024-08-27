WITH RECURSIVE
    node_rec AS (SELECT 1 AS row_count,
                        0 AS member_count,
                        1 AS depth,
                        organization.id,
                        organization.name,
                        organization.parent_org_id,
                        organization.default_job_limit_count,
                        organization.default_job_limit_hours,
                        organization.creation_date
                 FROM organization
                 WHERE organization.parent_org_id IS NULL
                 UNION ALL
                 SELECT 1 AS row_count,
                        0 AS member_count,
                        r.depth + 1,
                        n.id,
                        n.name,
                        n.parent_org_id,
                        n.default_job_limit_count,
                        n.default_job_limit_hours,
                        n.creation_date
                 FROM node_rec r
                          JOIN organization n ON n.parent_org_id = r.id) SEARCH DEPTH FIRST BY name,
    id SET path
 SELECT row_number() OVER (ORDER BY node_rec.path, node_rec.name) AS row_number,
    ( SELECT count(*) AS count
           FROM organization_membership
          WHERE organization_membership.org_id = node_rec.id) AS member_count,
    node_rec.depth,
    node_rec.id,
    node_rec.name,
    node_rec.default_job_limit_count,
    node_rec.default_job_limit_hours
   FROM node_rec
  WHERE node_rec.parent_org_id IS NOT NULL
  ORDER BY node_rec.path, node_rec.name