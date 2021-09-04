select distinct proc.order_proc_id_coded,
                proc.order_type,
                proc.proc_code,
                proc.description,
                proc.order_time_jittered_utc as proc_order_time,
                cohort.anon_id, cohort.pat_enc_csn_id_coded, cohort.admit_time, 
                cohort.first_label, cohort.death_24hr_recent_label
from
  triageTD.1_5_cohort_final as cohort,
  shc_core.order_proc as proc
where
  proc.order_type = 'Procedures'
  and cohort.anon_id = proc.anon_id
  and proc.order_time_jittered_utc < cohort.order_time_jittered_utc
  and timestamp_add(proc.order_time_jittered_utc, INTERVAL 24*365 HOUR) >= cohort.order_time_jittered_utc
order by pat_enc_csn_id_coded, organism, proc_order_time