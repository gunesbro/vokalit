"""Groups a dub's sentences by voice: one speaker embedding per sentence in, one speaker number per sentence out.
Pure (numpy and scipy), so it is tested without the model."""
import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

MIN_SPAN = 1.0  # seconds: shorter sentences are too short to tell voices apart, so they join the nearest group
THRESHOLD = 0.6  # cosine distance at which groups stop merging when the number of speakers is not given (a first guess)
MAX_CLUSTERED = 2000  # clustering needs every pairwise distance: past this, a sample is clustered and the rest join


def group(embeddings, durations, count=None):
    """Speaker numbers (0, 1, ... by first appearance) for each span; None for a span without sound (no embedding).
    `count`: how many speakers there are, or None to decide by THRESHOLD."""
    vectors = [None if e is None else np.asarray(e, dtype=np.float64) / max(np.linalg.norm(e), 1e-12)
               for e in embeddings]
    long = [i for i, v in enumerate(vectors) if v is not None and durations[i] >= MIN_SPAN]
    if len(long) > MAX_CLUSTERED:  # the longest span of each of MAX_CLUSTERED stretches of the file
        long = [max(chunk, key=lambda i: durations[i]) for chunk in np.array_split(long, MAX_CLUSTERED)]
    if len(long) < 2:
        raw = {i: 0 for i in long}
    else:
        tree = linkage(np.stack([vectors[i] for i in long]), method="average", metric="cosine")
        cut = fcluster(tree, t=min(count, len(long)), criterion="maxclust") if count \
            else fcluster(tree, t=THRESHOLD, criterion="distance")
        raw = dict(zip(long, cut))
    groups = sorted(set(raw.values()))
    centroids = []
    for g in groups:
        mean = np.mean([vectors[i] for i in raw if raw[i] == g], axis=0)
        centroids.append(mean / max(np.linalg.norm(mean), 1e-12))
    labels = []
    for i, v in enumerate(vectors):
        if v is None:
            labels.append(None)
        elif i in raw:
            labels.append(groups.index(raw[i]))
        elif centroids:
            labels.append(int(np.argmax([c @ v for c in centroids])))
        else:  # no long span at all: one speaker
            labels.append(0)
    order = {}  # renumbered by first appearance
    return [None if label is None else order.setdefault(label, len(order)) for label in labels]
