"""Explicit statistics for the frozen Hillstrom experiment contract."""
import math
from statistics import NormalDist


def check_binomial(x,n):
    if n<=0 or x<0 or x>n:raise ValueError('Invalid binomial counts.')


def wilson(x,n,alpha=.05):
    check_binomial(x,n)
    z=NormalDist().inv_cdf(1-alpha/2);p=x/n
    center=(p+z*z/(2*n))/(1+z*z/n)
    radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return max(0.,center-radius),min(1.,center+radius)


def newcombe(x1,n1,x0,n0,alpha=.05):
    check_binomial(x1,n1);check_binomial(x0,n0)
    p1,p0=x1/n1,x0/n0
    l1,u1=wilson(x1,n1,alpha);l0,u0=wilson(x0,n0,alpha)
    d=p1-p0
    return d-math.hypot(p1-l1,u0-p0),d+math.hypot(u1-p1,p0-l0)


def pooled_z_pvalue(x1,n1,x0,n0):
    check_binomial(x1,n1);check_binomial(x0,n0)
    pooled=(x1+x0)/(n1+n0)
    se=math.sqrt(pooled*(1-pooled)*(1/n1+1/n0))
    if se==0:return 1.0
    z=(x1/n1-x0/n0)/se
    return math.erfc(abs(z)/math.sqrt(2))


def holm(pvalues):
    if any(not 0<=p<=1 for p in pvalues):raise ValueError('Invalid probability.')
    order=sorted(range(len(pvalues)),key=lambda i:pvalues[i]);result=[0.]*len(pvalues)
    previous=0.
    for rank,i in enumerate(order):
        previous=max(previous,min(1.,(len(order)-rank)*pvalues[i]));result[i]=previous
    return result


def compare_binary(x1,n1,x0,n0):
    check_binomial(x1,n1);check_binomial(x0,n0)
    low,high=newcombe(x1,n1,x0,n0)
    return {'treatment_successes':int(x1),'treatment_n':int(n1),'control_successes':int(x0),'control_n':int(n0),
            'treatment_pct':100*x1/n1,'control_pct':100*x0/n0,'difference_pp':100*(x1/n1-x0/n0),
            'relative_lift_pct':100*((x1/n1)/(x0/n0)-1) if x0 else None,
            'ci_low_pp':100*low,'ci_high_pp':100*high,'p_raw':pooled_z_pvalue(x1,n1,x0,n0)}


def smd(mean1,var1,mean0,var0):
    sd=math.sqrt((var1+var0)/2)
    return (mean1-mean0)/sd if sd else (0. if mean1==mean0 else None)


def bootstrap_spend_means(cents,replicates,seed):
    """Exact ordinary row-bootstrap distribution, compressed by equal spend values."""
    import numpy as np
    rng=np.random.default_rng(seed)
    means={}
    for arm in ['No E-Mail','Mens E-Mail','Womens E-Mail']:
        a=np.asarray(cents[arm],dtype=np.int64)
        if len(a)==0 or np.any(a<0):raise ValueError('Nonempty nonnegative spend rows required.')
        values,frequency=np.unique(a,return_counts=True)
        output=[]
        for start in range(0,replicates,100):
            weights=rng.multinomial(len(a),frequency/len(a),size=min(100,replicates-start))
            output.append((weights@values)/(100*len(a)))
        means[arm]=np.concatenate(output)
    return means


def percentile_interval(values):
    import numpy as np
    a=np.asarray(values)
    if len(a)==0 or not np.all(np.isfinite(a)):raise ValueError('Finite nonempty draws required.')
    return [float(np.quantile(a,.025,method='linear')),float(np.quantile(a,.975,method='linear'))]
