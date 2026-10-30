"""User-cluster percentile intervals and separate product-cluster sensitivity."""
import json
from pathlib import Path

from intake import file_hash

ROOT=Path(__file__).resolve().parents[1]


def compress_vectors(vectors):
    import numpy as np
    a=np.asarray(vectors,dtype=np.int64)
    if a.ndim!=2 or len(a)==0 or a.shape[1]%2 or np.any(a<0):raise ValueError('Expected nonnegative count pairs.')
    if np.any(a[:,1::2]>a[:,0::2]):raise ValueError('Numerators exceed denominators.')
    if np.any(a[:,2::2]>a[:,0:1]) or np.any(a[:,3::2]>a[:,1:2]):raise ValueError('Target exceeds total.')
    return np.unique(a,axis=0,return_counts=True)


def bootstrap_totals(vectors,replicates,seed):
    import numpy as np
    patterns,frequency=compress_vectors(vectors)
    n=int(frequency.sum())
    rng=np.random.default_rng(seed)
    out=[]
    for start in range(0,replicates,100):
        weights=rng.multinomial(n,frequency/n,size=min(100,replicates-start))
        out.append(weights@patterns)
    return np.concatenate(out),len(patterns)


def contrast_values(totals,target_index):
    import numpy as np
    a=np.atleast_2d(np.asarray(totals))
    j=2+2*target_index
    def ratio(y,n):
        return np.divide(100*y,n,out=np.full(len(a),np.nan),where=n>0)
    target=ratio(a[:,j+1],a[:,j])
    rest=ratio(a[:,1]-a[:,j+1],a[:,0]-a[:,j])
    return target,rest,target-rest


def interval(values):
    import numpy as np
    valid=np.asarray(values)[np.isfinite(values)]
    return {'low':float(np.quantile(valid,.025,method='linear')) if len(valid) else None,
            'high':float(np.quantile(valid,.975,method='linear')) if len(valid) else None,
            'valid_replicates':int(len(valid)),'undefined_replicates':int(len(values)-len(valid))}


def main():
    import numpy as np
    from run_robustness import TARGETS
    payload=json.loads((ROOT/'reports/08_robustness_results.json').read_text())
    plan=payload['plan'];results=[];replicates=[]
    for metadata in payload['private_cluster_vectors']:
        path=ROOT/metadata['path']
        assert file_hash(path)==metadata['sha256']
        vectors=np.loadtxt(path,delimiter=',',skiprows=1,dtype=np.int64,ndmin=2)
        assert len(vectors)==metadata['clusters']
        boot,patterns=bootstrap_totals(vectors,plan['replicates'],plan['seed'])
        point=vectors.sum(axis=0)
        outpath=ROOT/f"data/work/08_{metadata['cluster']}_bootstrap_totals.npz"
        np.savez_compressed(outpath,totals=boot)
        replicates.append({'cluster':metadata['cluster'],'path':str(outpath.relative_to(ROOT)),'sha256':file_hash(outpath)})
        for i,(name,_) in enumerate(TARGETS):
            est=contrast_values(point,i);dist=contrast_values(boot,i)
            j=2+2*i
            row={'cluster':metadata['cluster'],'target':name,'clusters':len(vectors),
                 'target_nonempty_clusters':int(np.count_nonzero(vectors[:,j])),
                 'compressed_patterns':patterns,'target_denominator':int(point[j]),'target_numerator':int(point[j+1]),
                 'complement_denominator':int(point[0]-point[j]),'complement_numerator':int(point[1]-point[j+1]),
                 'largest_cluster_target_group_share_pct':100*int(vectors[:,j].max())/int(point[j])}
            for key,value,samples in zip(['target_pct','complement_pct','difference_pp'],est,dist):
                row[key]=float(value[0]);row[key+'_interval']=interval(samples)
                assert row[key+'_interval']['undefined_replicates']==0
            expected=next(r for r in payload['profiles']['scenarios'] if r['scenario']=='native_30' and r['target']==name)
            assert (row['target_denominator'],row['target_numerator'])==(expected['eligible_groups'],expected['purchase_groups'])
            results.append(row)
        print(f"{metadata['cluster']}: {len(vectors):,} clusters, {patterns:,} count patterns, {len(boot):,} replicates",flush=True)
    assert file_hash(ROOT/'data/processed/project01.sqlite')==payload['model_sha256']
    output={'chapter':'08','plan':plan,'results':results,'numpy_version':np.__version__,
            'input_results_sha256':file_hash(ROOT/'reports/08_robustness_results.json'),
            'bootstrap_code_sha256':file_hash(Path(__file__)),'private_replicates':replicates,
            'p_values_computed':False,'simultaneous_intervals':False,'causal_effects_computed':False}
    (ROOT/'reports/08_cluster_intervals.json').write_text(json.dumps(output,indent=2)+'\n')
    import csv
    flat=[]
    for row in results:
        item={k:v for k,v in row.items() if not isinstance(v,dict)}
        for key in ['target_pct','complement_pct','difference_pp']:
            item[key+'_low']=row[key+'_interval']['low'];item[key+'_high']=row[key+'_interval']['high']
        flat.append(item)
    with (ROOT/'reports/08_cluster_intervals.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
