from tqdm.auto import tqdm
import pandas as pd
import numpy as np
import torch
from ._utils import (
    _tokenize,
    _sequencize,
    _token2one_hot,
    _one_hot2token,
    _pad_sequences,
)  # modified concise
from ._utils import (
    _string_to_char_array,
    _one_hot_to_tokens,
    _char_array_to_string,
    _tokens_to_one_hot,
)  # dinuc_shuffle


# Vocabularies
DNA = ["A", "C", "G", "T"]
RNA = ["A", "C", "G", "U"]
COMPLEMENT_DNA = {"A": "T", "C": "G", "G": "C", "T": "A"}
COMPLEMENT_RNA = {"A": "U", "C": "G", "G": "C", "U": "A"}


def sanitize_seq(seq):
    """Make sure all letters are capitalized and remove whitespace for single seq."""
    return seq.strip().upper()


def sanitize_seqs(seqs):
    """Make sure all letters are capitalized and remove whitespace for multiple seqs."""
    return np.array([seq.strip().upper() for seq in seqs])


def ascii_encode(seq, pad=0):
    """
    Converts a string of characters to a NumPy array of byte-long ASCII codes.
    """
    encode_seq = np.array([ord(letter) for letter in seq], dtype=int)
    if pad > 0:
        encode_seq = np.pad(
            encode_seq, pad_width=(0, pad), mode="constant", constant_values=36
        )
    return encode_seq


def ascii_decode(seq):
    """
    Converts a NumPy array of byte-long ASCII codes to a string of characters.
    """
    return "".join([chr(int(letter)) for letter in seq]).replace("$", "")


def reverse_complement_seq(seq, vocab="DNA"):
    """Reverse complement a DNA sequence."""
    if vocab == "DNA":
        return "".join(COMPLEMENT_DNA.get(base, base) for base in reversed(seq))
    elif vocab == "RNA":
        return "".join(COMPLEMENT_RNA.get(base, base) for base in reversed(seq))
    else:
        raise ValueError("Invalid vocab, only DNA or RNA are currently supported")


def reverse_complement_seqs(seqs, vocab="DNA", verbose=True):
    """Reverse complement a list of sequences."""
    return np.array(
        [
            reverse_complement_seq(seq, vocab)
            for i, seq in tqdm(
                enumerate(seqs),
                total=len(seqs),
                desc="Reverse complementing sequences",
                disable=not verbose,
            )
        ]
    )


def ohe_seq(seq, vocab="DNA", neutral_vocab="N", fill_value=0):
    """Convert a DNA or RNA sequence into one-hot-encoded array."""
    seq = seq.strip().upper()
    return _token2one_hot(
        _tokenize(seq, vocab, neutral_vocab), vocab, fill_value=fill_value
    )


def ohe_seqs(
    seqs,
    vocab="DNA",
    neutral_vocab="N",
    maxlen=None,
    pad=True,
    pad_value="N",
    fill_value=None,
    seq_align="start",
    verbose=True
):
    if isinstance(neutral_vocab, str):
        neutral_vocab = [neutral_vocab]
    if isinstance(seqs, str):
        raise ValueError("seq_vec should be an iterable not a string itself")
    assert len(vocab[0]) == len(pad_value)
    assert pad_value in neutral_vocab
    if pad:
        seqs_vec = _pad_sequences(
            seqs, maxlen=maxlen, align=seq_align, value=pad_value
        )
    arr_list = [
        ohe_seq(
            seq=seqs_vec[i],
            vocab=vocab,
            neutral_vocab=neutral_vocab,
            fill_value=fill_value,
        )
        for i in tqdm(
            range(len(seqs_vec)),
            total=len(seqs_vec),
            desc="One-hot encoding sequences",
            disable=not verbose,
        )
    ]
    if pad:
        return np.stack(arr_list)
    else:
        return np.array(arr_list, dtype=object)


def decode_seq(arr, vocab="DNA", neutral_value=-1, neutral_char="N"):
    """Convert a one-hot encoded array back to string"""
    return _sequencize(
        tvec=_one_hot2token(arr, neutral_value), 
        vocab=vocab, 
        neutral_value=neutral_value, 
        neutral_char=neutral_char
    )


def decode_seqs(
    arr, 
    vocab="DNA", 
    neutral_char="N",
    neutral_value=-1,
    verbose=True
):
    """Convert a one-hot encoded array back to string"""
    arr_list = [
        decode_seq(
            arr=arr[i],
            vocab=vocab,
            neutral_value=neutral_value,
            neutral_char=neutral_char,
        )
        for i in tqdm(
            range(len(arr)),
            total=len(arr),
            desc="Decoding sequences",
            disable=not verbose,
        )
    ]
    return np.array(arr_list)


def dinuc_shuffle_seq(seq, num_shufs=None, rng=None):
    """
    Creates shuffles of the given sequence, in which dinucleotide frequencies
    are preserved.
    Arguments:
        `seq`: either a string of length L, or an L x D np array of one-hot
            encodings
        `num_shufs`: the number of shuffles to create, N; if unspecified, only
            one shuffle will be created
        `rng`: a np RandomState object, to use for performing shuffles
    If `seq` is a string, returns a list of N strings of length L, each one
    being a shuffled version of `seq`. If `seq` is a 2D np array, then the
    result is an N x L x D np array of shuffled versions of `seq`, also
    one-hot encoded. If `num_shufs` is not specified, then the first dimension
    of N will not be present (i.e. a single string will be returned, or an L x D
    array).
    """
    if type(seq) is str or type(seq) is np.str_:
        arr = _string_to_char_array(seq)
    elif type(seq) is np.ndarray and len(seq.shape) == 2:
        seq_len, one_hot_dim = seq.shape
        arr = _one_hot_to_tokens(seq)
    else:
        raise ValueError("Expected string or one-hot encoded array")

    if not rng:
        rng = np.random.RandomState()

    # Get the set of all characters, and a mapping of which positions have which
    # characters; use `tokens`, which are integer representations of the
    # original characters
    chars, tokens = np.unique(arr, return_inverse=True)

    # For each token, get a list of indices of all the tokens that come after it
    shuf_next_inds = []
    for t in range(len(chars)):
        mask = tokens[:-1] == t  # Excluding last char
        inds = np.where(mask)[0]
        shuf_next_inds.append(inds + 1)  # Add 1 for next token

    if type(seq) is str or type(seq) is np.str_:
        all_results = []
    else:
        all_results = np.empty(
            (num_shufs if num_shufs else 1, seq_len, one_hot_dim), dtype=seq.dtype
        )

    for i in range(num_shufs if num_shufs else 1):
        # Shuffle the next indices
        for t in range(len(chars)):
            inds = np.arange(len(shuf_next_inds[t]))
            inds[:-1] = rng.permutation(len(inds) - 1)  # Keep last index same
            shuf_next_inds[t] = shuf_next_inds[t][inds]

        counters = [0] * len(chars)

        # Build the resulting array
        ind = 0
        result = np.empty_like(tokens)
        result[0] = tokens[ind]
        for j in range(1, len(tokens)):
            t = tokens[ind]
            ind = shuf_next_inds[t][counters[t]]
            counters[t] += 1
            result[j] = tokens[ind]

        if type(seq) is str or type(seq) is np.str_:
            all_results.append(_char_array_to_string(chars[result]))
        else:
            all_results[i] = _tokens_to_one_hot(chars[result], one_hot_dim)
    return all_results if num_shufs else all_results[0]


def dinuc_shuffle_seqs(seqs, num_shufs=None, rng=None):
    """
    Shuffle the sequences in `seqs` in the same way as `dinuc_shuffle_seq`.
    If `num_shufs` is not specified, then the first dimension of N will not be
    present (i.e. a single string will be returned, or an L x D array).
    """
    if not rng:
        rng = np.random.RandomState()

    if type(seqs) is str or type(seqs) is np.str_:
        seqs = [seqs]

    all_results = []
    for i in range(len(seqs)):
        all_results.append(dinuc_shuffle_seq(seqs[i], num_shufs=num_shufs, rng=rng))
    return np.array(all_results)


# modified yuzu
def perturb_seqs(X_0, vocab_len=4):
    """Produce all edit-distance-one pertuabtions of a sequence.
    This function will take in a single one-hot encoded sequence of length N
    and return a batch of N*(n_choices-1) sequences, each containing a single
    perturbation from the given sequence.
    Parameters
    ----------
    X_0: np.ndarray, shape=(n_seqs, n_choices, seq_len)
        A one-hot encoded sequence to generate all potential perturbations.
    Returns
    -------
    X: torch.Tensor, shape=(n_seqs, (n_choices-1)*seq_len, n_choices, seq_len)
        Each single-position perturbation of seq.
    """
    import warnings
    if not isinstance(X_0, np.ndarray):
        raise ValueError("X_0 must be of type np.ndarray, not {}".format(type(X_0)))

    if len(X_0.shape) != 3:
        raise ValueError(
            "X_0 must have three dimensions: (n_seqs, n_choices, seq_len)."
        )
    if X_0.shape[1] != 4:
        warnings.warn(
            "X_0 has {} choices, but should have 4. Transposing".format(X_0.shape[1])
        )
        X_0 = X_0.transpose(0, 2, 1)

    n_seqs, n_choices, seq_len = X_0.shape
    idxs = X_0.argmax(axis=1)

    X_0 = torch.from_numpy(X_0)

    n = seq_len * (n_choices - 1)
    X = torch.tile(X_0, (n, 1, 1))
    print(X.shape)
    X = X.reshape(n, n_seqs, n_choices, seq_len).permute(1, 0, 2, 3)
    print(X.shape)

    for i in range(n_seqs):
        for k in range(1, n_choices):
            idx = np.arange(seq_len) * (n_choices - 1) + (k - 1)

            X[i, idx, idxs[i], np.arange(seq_len)] = 0
            X[i, idx, (idxs[i] + k) % n_choices, np.arange(seq_len)] = 1

    return X


def feature_implant_seq(seq, feature, position, encoding="str", onehot=False):
    """
    Insert a feature at a given position in a sequence.
    """
    if encoding == "str":
        return seq[:position] + feature + seq[position + len(feature) :]
    elif encoding == "onehot":
        if onehot:
            feature = _token2one_hot(feature.argmax(axis=1), vocab_size=4, fill_value=0)
        return np.concatenate(
            (seq[:position], feature, seq[position + len(feature) :]), axis=0
        )
    else:
        raise ValueError("Encoding not recognized.")


def feature_implant_across_seq(seq, feature, **kwargs):
    """
    Insert a feature at every position in a sequence.
    """
    implanted_seqs = []
    for pos in range(len(seq) - len(feature) + 1):
        implanted_seqs.append(feature_implant_seq(seq, feature, pos, **kwargs))
    return np.array(implanted_seqs)
