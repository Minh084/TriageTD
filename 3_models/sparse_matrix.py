# Developed by Conor Corbin, modified by Minh Nguyen

import pandas as pd
import numpy as np
import os, argparse

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/home/jupyter/.config/gcloud/application_default_credentials.json'
os.environ['GCLOUD_PROJECT'] = 'som-nero-phi-jonc101' 

from google.cloud import bigquery
client=bigquery.Client()

from scipy.sparse import csr_matrix, save_npz
import pdb

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output_path', type=str,
                        help='base path to output sparse matrices')
    parser.add_argument('--cohort', type=str, 
                        help='which cohort to use')
    args = parser.parse_args()

    base_path = args.output_path
    out_path = os.path.join(base_path, args.cohort)
    os.makedirs(out_path, exist_ok=True)

    ### make queries, use appropriate cohort: 1_4_cohort or 1_5_cohort_final
    if args.cohort == "1_4_cohort":
        q_cohort = """SELECT * FROM triageTD.1_4_cohort"""
        q_features = """SELECT * FROM triageTD.2_9_coh4_features_all_long_year""" 
    else:
        q_cohort = """SELECT * FROM triageTD.1_5_cohort_final"""
        q_features = """SELECT * FROM triageTD.2_9_coh5_features_all_long_year""" 

#     anon_id, pat_enc_csn_id_coded, admit_time, first_label, death_24hr_recent_label, death_24hr_max_label

#     q_features = """
#     SELECT f.*, EXTRACT(YEAR from f.admit_time) year
#     FROM triageTD.2_9_features_all_long f
#     RIGHT JOIN triageTD.1_5_cohort_final c
#     USING (pat_enc_csn_id_coded)
#     """

    # this one only has trainbin for vitals and labs
#     q_features = """SELECT * FROM triageTD.2_9_features_all_long""" 

    # this one has both trainbin and testbin for vitals and labs
#     q_features = """SELECT * FROM triageTD.2_9_features_all_long_year""" # this breaks the index alignment
    
    # this one uses 1_4_cohort
#     q_features = """SELECT * FROM triageTD.2_9_coh4_features_all_long_year""" # this breaks the index alignment
    
#     q_features = """
#     SELECT f.* FROM triageTD.2_9_coh4_features_all_long_year f
#     RIGHT JOIN triageTD.1_4_cohort c
#     USING (pat_enc_csn_id_coded)
#     """ 

    ### query to dataframes
    query_job = client.query(q_cohort)
    df_cohort = query_job.result().to_dataframe()
    df_cohort = df_cohort.sort_values('pat_enc_csn_id_coded')
    print(len(df_cohort.pat_enc_csn_id_coded.unique()))
    
    query_job = client.query(q_features)
    df_features = query_job.result().to_dataframe()
    df_features = df_features.sort_values('pat_enc_csn_id_coded') 
    print(len(df_features.pat_enc_csn_id_coded.unique()))
    
    ### Save labels to file
    train_labels = df_cohort[df_cohort['admit_time'].dt.year < 2018]
    validation_labels = df_cohort[df_cohort['admit_time'].dt.year == 2018]

    train_and_val_labels = df_cohort[df_cohort['admit_time'].dt.year < 2019]
    test_labels = df_cohort[df_cohort['admit_time'].dt.year >= 2019] # new data has 2020
    
    train_labels.to_csv(os.path.join(out_path, 'training_labels.csv'), index=None)
    validation_labels.to_csv(os.path.join(out_path, 'validation_labels.csv'), index=None)
    train_and_val_labels.to_csv(os.path.join(out_path, 'train_and_val_labels.csv'), index=None)
    test_labels.to_csv(os.path.join(out_path, 'test_labels.csv'), index=None)
    

    ### Remove appropriate binned features to create matrices for train (train and val) or test (train_val and test)
    df_features_val = df_features[~df_features['feature_type'].isin(['labs_results_test', 'vitals_test'])]
    df_features_test = df_features[~df_features['feature_type'].isin(['labs_results_train', 'vitals_train'])]
    
    training_examples = df_features_val[df_features_val['year'] < 2018]
    validation_examples = df_features_val[df_features_val['year'] == 2018]
    
    training_and_val_examples = df_features_test[df_features_test['year'] < 2019]
    test_examples = df_features_test[df_features_test['year'] >= 2019]

    
    ### Create sparse matrix representations
    train_csr, train_csns, train_vocab = create_sparse_feature_matrix(training_examples, training_examples)
    validation_csr, val_csns, val_vocab = create_sparse_feature_matrix(training_examples, validation_examples)

    train_and_val_csr, train_and_val_csns, train_and_val_vocab = create_sparse_feature_matrix(training_and_val_examples, training_and_val_examples)
    test_csr, test_csns, test_and_val_vocab = create_sparse_feature_matrix(training_and_val_examples, test_examples)
    
    ### Sanity checks
    for a, b in zip(train_labels['pat_enc_csn_id_coded'].values, train_csns):
        assert a == b
    for a, b in zip(validation_labels['pat_enc_csn_id_coded'].values, val_csns):
        assert a == b
    for a, b in zip(train_and_val_labels['pat_enc_csn_id_coded'].values, train_and_val_csns):
        assert a == b
    for a, b in zip(test_labels['pat_enc_csn_id_coded'].values, test_csns):
        assert a == b
    
    save_npz(os.path.join(out_path, 'training_examples.npz'), train_csr)
    save_npz(os.path.join(out_path, 'validation_examples.npz'), validation_csr)
    save_npz(os.path.join(out_path, 'training_and_val_examples.npz'), train_and_val_csr)
    save_npz(os.path.join(out_path, 'test_examples.npz'), test_csr)

    
def build_vocab(data):
    """Builds vocabulary for of terms from the data. Assigns each unique term to a monotonically increasing integer."""
    vocabulary = {}
    for i, d in enumerate(data):
        for j, term in enumerate(d):
            vocabulary.setdefault(term, len(vocabulary))
    return vocabulary


def create_sparse_feature_matrix(train_data, apply_data):
    """Creates sparse matrix efficiently from long form dataframe.  We build a vocabulary
       from the training set, then apply vocab to the apply_set
       
       Parameters
       ----------
       train_data : long form pandas DataFrame
           Data to use to build vocabulary
       apply_data : long form pandas DataFrame
           Data to transform to sparse matrix for input to ML models
    
       Returns
       -------
       csr_data : scipy csr_matrix
           Sparse matrix version of apply_data to feed into ML models. 
    """
    
    train_features = train_data.groupby('pat_enc_csn_id_coded').agg({
        'features' : lambda x: list(x),
        'values' : lambda x: list(x)}).reset_index()
    train_feature_names = [doc for doc in train_features.features.values]
    train_feature_values = [doc for doc in train_features['values'].values]
    train_csns = [csn for csn in train_features.pat_enc_csn_id_coded.values]
    
    apply_features = apply_data.groupby('pat_enc_csn_id_coded').agg({
        'features' : lambda x: list(x),
        'values' : lambda x: list(x)}).reset_index()
    apply_features_names = [doc for doc in apply_features.features.values]
    apply_features_values = [doc for doc in apply_features['values'].values]
    apply_csns = [csn for csn in apply_features.pat_enc_csn_id_coded.values]

    
    vocabulary = build_vocab(train_feature_names)
    indptr = [0]
    indices = []
    data = []
    for i, d in enumerate(apply_features_names):
        for j, term in enumerate(d):
            if term not in vocabulary:
                continue
            else:
                indices.append(vocabulary[term])
                data.append(apply_features_values[i][j])
            if j == 0:
                # Add zero to data and max index in vocabulary to indices in case max feature indice isn't in apply features.
                indices.append(len(vocabulary)-1)
                data.append(0)
        indptr.append(len(indices))
    
    csr_data = csr_matrix((data, indices, indptr), dtype=float)
    
    return csr_data, apply_csns, vocabulary


if __name__=="__main__":
    main()
