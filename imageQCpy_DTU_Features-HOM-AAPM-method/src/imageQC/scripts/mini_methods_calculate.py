#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Collection of small functions used in ImageQC.

@author: Ellen Wasbo
"""
import numpy as np
from scipy.optimize import curve_fit
from scipy.ndimage import gaussian_filter, rotate
from scipy.ndimage import geometric_transform
from scipy.signal import convolve2d


def get_distance_map_point(shape, center_dx=0., center_dy=0.):
    """Calculate distances from center point in image (optionally with offset).

    Parameters
    ----------
    shape : tuple
        shape of array to generate
    center_dx : float, optional
        offset from center in shape. The default is 0..
    center_dy : float, optional
        offset from center in shape. The default is 0..

    Returns
    -------
    distance_map : ndarray
        of shape equal to input shape
    """
    sz_y, sz_x = shape
    xs, ys = np.meshgrid(np.arange(sz_x), np.arange(sz_y))
    center_pos_x = center_dx + 0.5 * sz_x
    center_pos_y = center_dy + 0.5 * sz_y
    distance_map = np.sqrt((xs-center_pos_x) ** 2 + (ys-center_pos_y) ** 2)

    return distance_map


def get_distance_map_edge(shape, slope=0., intercept=0., vertical_positions=None):
    """Calculate distances from edge defined by y = ax + b.

    distance from x0,y0 normal to line = (b + a*x0 - y0)/sqrt(1+a^2)
    https://en.wikipedia.org/wiki/Distance_from_a_point_to_

    Parameters
    ----------
    shape : tuple
        shape of 2darray to generate map for
    slope : float, optional
        a in y = ax + b. The default is 0.
    intercept : float, optional
        b in y = ax + b. The default is 0.
    vertical_positions : list of float, optional
        y-pos in unit x-pix. If None assume y pix = x pix. Default is None.

    Returns
    -------
    distance_map : 2darray
        of shape equal to input shape
    """
    sz_y, sz_x = shape
    y_array = np.arange(sz_y)
    if isinstance(vertical_positions, list):
        if sz_y == len(vertical_positions):
            y_array = np.array(vertical_positions)
    xs, ys = np.meshgrid(np.arange(sz_x), y_array)
    distance_map = (ys - intercept - slope*xs) / np.sqrt(1 + slope**2)

    return distance_map


def gauss_4param(x, H, A, x0, sigma):
    """Calculate gaussian curve from x values and parameters."""
    return H + A * np.exp(-(x - x0) ** 2 / (2 * sigma ** 2))


def gauss_4param_fit(x, y):
    """Fit x,y to gaussian curve."""
    mean = sum(x * y) / sum(y)
    sigma = np.sqrt(sum(y * (x - mean) ** 2) / sum(y))
    try:
        popt, _ = curve_fit(gauss_4param, x, y, p0=[min(y), max(y), mean, sigma])
    except RuntimeError:  # consider ValueError if not strictly increasing
        popt = None
    return popt


def gauss(x, A, sigma):
    """Calculate gaussian curve from x values and parameters."""
    return A * np.exp(-0.5 * (x ** 2) / (sigma ** 2))


def gauss_fit(x, y, fwhm=0):
    """Fit x,y to gaussian curve."""
    if fwhm == 0:
        width, _ = get_width_center_at_threshold(y, np.max(y)/2)
        if width is not None:
            fwhm = width * (x[1] - x[0])
    sigma = fwhm / (2 * np.sqrt(2 * np.log(2)))
    A = max(y)
    try:
        popt, _ = curve_fit(
            gauss, x, y, p0=[A, sigma],
            bounds=([0.9*A, 0.5*sigma], [1.1*A, 2*sigma])
            )
    except RuntimeError:  # consider ValueError if not strictly increasing
        popt = None
    return popt


def gauss_double(x, A1, sigma1, A2, sigma2):
    """Calculate sum of two centered gaussian curves."""
    return (A1 * np.exp(-(x) ** 2 / (2 * sigma1 ** 2)) +
            A2 * np.exp(-(x) ** 2 / (2 * sigma2 ** 2)))


def gauss_double_fit(x, y, fwhm1=None, A2_positive=False):
    """Fit x,y to centered double gaussian.

    Parameters
    ----------
    x : np.1darray
    y : np.1darray
    fwhm1 : float, optional
        Option to specify fwhm1 to calculate sigma1. The default is 0.
    A2_positive : bool, optional
        If false: either A1 positive and A2 negative or fit to single gaussian (CT LSF).
        If true: force both A1 and A2 positive (Xray LSF).
        The default is False.

    Returns
    -------
    popt from scipy.optimize.curve_fit
    """
    if fwhm1 is None:
        width, _ = get_width_center_at_threshold(y, np.max(y)/2)
        if width is not None:
            fwhm1 = width * (x[1] - x[0])
    sigma1 = fwhm1 / (2 * np.sqrt(2 * np.log(2)))

    if A2_positive:
        A1 = 0.9 * np.max(y)
        A2 = 0.1 * np.max(y)
        sigma = sigma1
        try:
            popt, _ = curve_fit(
                gauss_double, x, y, p0=[A1, sigma, A2, sigma],
                bounds=([0.5*A1, 0.7*sigma, 0, 0.7*sigma],
                        [2*A1, 2*sigma, 2*A1, 3*sigma]),
                )
        except RuntimeError:
            popt = None
    else:
        A1 = np.max(y) - 2 * np.min(y)
        A2 = 2 * np.min(y)
        sigma2 = 2 * sigma1
        try:
            if A2 < 0:
                popt, pcov = curve_fit(
                    gauss_double, x, y, p0=[A1, sigma1, A2, sigma2],
                    bounds=([0.5*A1, 0.5*sigma1, 2*A2, 0.5*sigma2],
                            [2*A1, 2*sigma1, 0, 2*sigma2]),
                    )
            else:
                A1 = max(y)
                popt, pcov = curve_fit(
                    gauss, x, y, p0=[A1, sigma1],
                    bounds=([0.5*A1, 0.5*sigma1], [2*A1, 2*sigma1]),
                    )
        except RuntimeError:
            popt = None
    return popt


def polyfit_2d(array_2d, max_order=2):
    """Fit 2d array to polynomial plane.

    https://scipython.com/blog/linear-least-squares-fitting-of-a-two-dimensional-data/

    Parameters
    ----------
    array_2d : np.array
    max_order : int
        max polynomial order

    Returns
    -------
    fitted_2darray
    """
    def get_basis(x, y, max_order=2):
        """Return the fit basis polynomials: 1, x, x^2, ..., xy, x^2y, ... etc."""
        basis = []
        for i in range(max_order+1):
            for j in range(max_order - i + 1):
                basis.append(x**j * y**i)
        return basis
    sz_y, sz_x = array_2d.shape
    xs, ys = np.meshgrid(np.arange(sz_x), np.arange(sz_y))
    basis = get_basis(xs.ravel(), ys.ravel(), max_order)
    # Linear, least-squares fit.
    A = np.vstack(basis).T
    b = array_2d.ravel()
    c, _, _, _ = np.linalg.lstsq(A, b, rcond=None)

    # Calculate the fitted surface from the coefficients, c.
    fitted_2darray = np.sum(c[:, None, None] * np.array(get_basis(xs, ys, max_order))
                            .reshape(len(basis), *xs.shape), axis=0)

    return fitted_2darray


def get_MTF_gauss(LSF, dx=1., prefilter_sigma=None, gaussfit='single'):
    """Fit LSF to gaussian and calculate gaussian MTF.

    Parameters
    ----------
    LSF : np.array
        LSF 1d
    dx : float, optional
        step_size, default is 1.
    prefilter_sigma : float, optional
        prefiltered with gaussian filter, sigma=prefilter_sigma. The default is None.
    gaussfit : str, optional
        single or double or double_allow_both_positive (sum of two gaussian).
        double assume by default 1 negative + 1 positive gauss.
        double_both_positive demand both positive.
        The default is 'single'.

    Returns
    -------
    dict
        with calculation details
    str
        error message
    """
    popt = None
    details = {}
    errmsg = None
    width, center = get_width_center_at_threshold(LSF, 0.5 * max(LSF))
    if center is None:
        errmsg = 'Failed finding center of LSF.'
    else:
        LSF_x = dx * (np.arange(LSF.size) - center)
        A2 = None
        sigma2 = None
        if gaussfit == 'double':
            popt = gauss_double_fit(LSF_x, LSF, fwhm1=width * dx)
            if popt is not None:
                if len(popt) == 4:
                    A1, sigma1, A2, sigma2 = popt
                    LSF_fit = gauss_double(LSF_x, *popt)
                else:
                    A1, sigma1 = popt
                    LSF_fit = gauss(LSF_x, *popt)
        elif gaussfit == 'double_both_positive':
            popt = gauss_double_fit(LSF_x, LSF, fwhm1=width * dx, A2_positive=True)
            if popt is not None:
                A1, sigma1, A2, sigma2 = popt
                LSF_fit = gauss_double(LSF_x, *popt)
        else:  # single
            popt = gauss_fit(LSF_x, LSF)
            if popt is not None:
                LSF_fit = gauss(LSF_x, *popt)
                A1, sigma1 = popt

        if popt is None:
            errmsg = 'Failed fitting LSF to gaussian.'
        else:
            n_steps = 200  # sample 20 steps from 0 to 1 stdv MTF curve (stdev = 1/sigma1)
            # TODO user configurable n_steps
            k_vals = np.arange(n_steps) * (10./n_steps) / sigma1
            MTF = gauss(k_vals, A1*sigma1, 1/sigma1)
            if A2 is not None and sigma2 is not None:
                F2 = gauss(k_vals, A2*sigma2, 1/sigma2)
                MTF = np.add(MTF, F2)
            MTF_filtered = None
            if prefilter_sigma is None:
                prefilter_sigma = 0
            if prefilter_sigma > 0:
                F_filter = gauss(k_vals, 1., 1/prefilter_sigma)
                MTF_filtered = 1/MTF[0] * MTF  # for display
                MTF = np.divide(MTF, F_filter)
            MTF = 1/MTF[0] * MTF
            k_vals = k_vals / (2*np.pi)

            fwhm = None
            fwtm = None
            LSF_corrected = None
            if gaussfit == 'single':
                if prefilter_sigma == 0:
                    fwhm = 2*np.sqrt(2*np.log(2))*sigma1
                    fwtm = 2*np.sqrt(2*np.log(10))*sigma1
                else:
                    # Gaussian fit of the corrected MTF
                    k_vals_symmetric = np.concatenate((-k_vals[::-1], k_vals[1:]))
                    MTF_symmetric = np.concatenate((MTF[::-1], MTF[1:]))
                    poptMTF = gauss_fit(k_vals_symmetric, MTF_symmetric)
                    if poptMTF is not None:
                        _, sigmaMTF = poptMTF
                        LSF_corrected = gauss(
                            LSF_x, np.max(LSF_fit), 1/(2*np.pi*sigmaMTF))
                        LSF_sigma = 1./(2*np.pi*sigmaMTF)
                        fwhm = 2*np.sqrt(2*np.log(2))*LSF_sigma
                        fwtm = 2*np.sqrt(2*np.log(10))*LSF_sigma

            details = {
                'LSF_fit_x': LSF_x, 'LSF_fit': LSF_fit, 'LSF_prefit': LSF,
                'LSF_corrected': LSF_corrected,
                'LSF_fit_params': popt,
                'MTF_freq': k_vals, 'MTF': MTF, 'MTF_filtered': MTF_filtered,
                'FWHM': fwhm, 'FWTM': fwtm,
                }

    return (details, errmsg)


def get_MTF_discrete(LSF, dx=1, padding_factor=1):
    """Fourier transform of vector with zero-padding.

    Parameters
    ----------
    LSF : np.array of floats
        line spread function
    dx : float
        stepsize in LSF
    padding_factor: float, optional
        zero-pad each side by padding-factor * length of LSF. Default is 1.

    Returns
    -------
    freq : np.array of float
        frequency axis of MTF
    MTF : np.array of float
        modulation transfer function
    """
    nLSF = round(padding_factor * LSF.size)
    LSF = np.pad(LSF, pad_width=nLSF, mode='constant', constant_values=0)
    MTF = np.abs(np.fft.fft(LSF))
    freq = np.fft.fftfreq(LSF.size, d=dx)
    MTF = MTF[:MTF.size//2]
    freq = freq[:freq.size//2]
    MTF = MTF/MTF[0]

    return {'MTF_freq': freq, 'MTF': MTF}


def get_2d_NPS(sub_image, pix, zero_padding=False):
    """Calculate fourier transform of 2d array."""
    if zero_padding:
        fourier = np.fft.fft2(
            np.pad(sub_image, (sub_image.shape, sub_image.shape), 'constant'))
    else:
        fourier = np.fft.fft2(sub_image)
    fourier = np.fft.fftshift(fourier)
    if zero_padding:
        factor = pix**2 / (3 * sub_image.shape[0] * 3 * sub_image.shape[1])
    else:
        factor = pix**2 / (sub_image.shape[0] * sub_image.shape[1])
    return factor * np.abs(fourier) ** 2


def get_NPSuv_profile(NPS_array, nlines=7, exclude_axis=True, pix=1., step_size=None):
    """Extract horizontal and vertical 1d NPS.

    Parameters
    ----------
    NPS_array : np.2darray
    nlines : int, optional
        number of lines to include at each side. The default is 7.
    exclude_axis : bool, optional
        exclude line at axis (often very high). The default is True.
    pix : float, optional
        pixelsize of image. The default is 1..
    step_size : float, optional
        sampling step size for curves. The default is None = no resampling.

    Returns
    -------
    freq : np.1darray
        frequency axis
    u_profile : np.1darray
        horizontal NPS
    v_profile : np.1darray
        vertical NPS
    """
    if exclude_axis:
        lines = np.arange(nlines) + 1
        lines = NPS_array.shape[0] // 2 + np.concatenate((-np.flip(lines), lines))
    else:
        lines = np.arange(nlines)
        lines = NPS_array.shape[0] // 2 + np.concatenate((-np.flip(lines[1:]), lines))
    u_profile = np.mean(NPS_array[lines], axis=0)
    v_profile = np.mean(NPS_array[:][:, lines], axis=1)

    u_profile = np.fft.fftshift(u_profile)
    v_profile = np.fft.fftshift(v_profile)
    freq = np.fft.fftfreq(NPS_array.shape[0], d=pix)

    # skip symmetry part and zero value
    u_profile = u_profile[1:NPS_array.shape[0] // 2]
    v_profile = v_profile[1:NPS_array.shape[0] // 2]
    freq = freq[1:NPS_array.shape[0] // 2]

    if step_size is not None:
        freq_new, u_profile = resample_by_binning(
            u_profile, freq, step_size, first_step=freq[1])
        freq_new, v_profile = resample_by_binning(
            v_profile, freq, step_size, first_step=freq[1])
        freq = freq_new
    return (freq, u_profile, v_profile)


def get_radial_profile(array_2d, pix=1., start_dist=0, stop_dist=None,
                       step_size=1., ignore_negative=False):
    """Calculate radial profile of image.

    Parameters
    ----------
    array_2d : np.2darray
        image to calculate radial profile from
    pix : float, optional
        Pixel size to scale x axis. The default is 1..
    start_dist : float, optional
        set other than 0 to skip values close to center. The default is 0.
        dist scaled to same unit as pix
    stop_dist : float or None, optional
        set other than None to skip values at larger distances. The default is None.
        dist scaled to same unit as pix
    step_size: float
        step size (sampling frequency) of profile
    ignore_negative : bool
        True = set negative values to zero. Default is False.

    Returns
    -------
    radial_profile_x : np.1darray
        x values
    radial_profile : np.1darray
        profile values
    """
    # sort pixel values from center
    dist_map = get_distance_map_point(array_2d.shape, center_dx=-0.5, center_dy=-0.5)
    dists_flat = dist_map.flatten()
    sort_idxs = np.argsort(dists_flat)
    dists = pix * dists_flat[sort_idxs]
    values_flat = array_2d.flatten()[sort_idxs]

    # ignore dists?
    if stop_dist is not None:
        dists_cut_temp = dists[dists < stop_dist]
        values_temp = values_flat[dists < stop_dist]
    else:
        dists_cut_temp = dists
        values_temp = values_flat
    if start_dist > 0:
        dists_cut = dists_cut_temp[dists_cut_temp > start_dist]
        values = values_temp[dists_cut_temp > start_dist]
    else:
        dists_cut = dists_cut_temp
        values = values_temp

    radial_profile_x, radial_profile = resample_by_binning(
        values, dists_cut, step_size, first_step=start_dist)

    if ignore_negative:
        radial_profile[radial_profile < 0] = 0

    return (radial_profile_x, radial_profile)


def find_median_spectrum(x, y):
    """Find frequency that split spectrum in two (same area)."""
    cumsum = np.cumsum(y)
    find_median = np.where(cumsum > np.max(cumsum)/2)
    median_x = x[find_median[0][0]]
    median_y = y[find_median[0][0]]
    return (median_x, median_y)


def point_source_func(x, C, D):
    """Calculate foton fluence from point source measured by detector.

    Based on equation A6 in
    https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3966082/#x0
    """
    return C * D / ((x**2 + D**2)**(1.5))


def point_source_func_fit(x, y, center_value=0., avg_radius=0., lock_radius=False):
    """Fit foton fluence from point source at detector."""
    C = center_value*avg_radius**2
    if lock_radius:
        popt, pcov = curve_fit(point_source_func, x, y,
                               p0=[C, avg_radius],
                               bounds=([0.5*C, avg_radius], [1.5*C, avg_radius+0.01])
                               )
    else:
        try:
            popt, pcov = curve_fit(point_source_func, x, y,
                                   p0=[C, avg_radius])
        except RuntimeError:
            popt = None
    return popt


def center_xy_of_disc(matrix2d, threshold=None, roi=None, mode='mean', sigma=5.):
    """Find center of disc (or point) object in image.

    Robust against noise and returning sub pixel precision center.

    Parameters
    ----------
    matrix2d : np.array of float
        2 dimensions
    threshold : float, optional
        value to differ inside/outside disc. The default is None.
        if None use halfmax (value between min, max)
    roi : np.array of bool, optional
        ignore pixels outside roi
    mode : str, optional
        Mean, max or max_or_min. If max or min np.min if center signal low.
        Default is 'mean'.
    sigma : float, options
        smooth by gaussian filter before finding center.
        NB - might drag signal to one side

    Returns
    -------
    center_x : float
    center_y : float
    """
    center_xy = []
    smoothed_matrix = gaussian_filter(matrix2d, sigma=sigma)
    if roi is not None:
        smoothed_matrix = np.ma.masked_array(smoothed_matrix, mask=np.invert(roi))
    # smoothed mean or max profile (within ROI) to estimate center
    for ax in [0, 1]:
        if mode == 'mean':
            prof1 = np.mean(smoothed_matrix, axis=ax)
        elif mode == 'max_or_min':  # min if center signal lower than outer
            sz_y, sz_x = smoothed_matrix.shape
            inner = smoothed_matrix[
                sz_y // 2 - sz_y // 4: sz_y // 2 + sz_y // 4,
                sz_x // 2 - sz_x // 4: sz_x // 2 + sz_x // 4]
            if np.mean(inner) < np.mean(smoothed_matrix):
                prof1 = np.min(smoothed_matrix, axis=ax)
            else:
                prof1 = np.max(smoothed_matrix, axis=ax)
        else:
            prof1 = np.max(smoothed_matrix, axis=ax)
        if threshold is None:
            threshold = np.min(prof1) + 0.5 * (np.max(prof1) - np.min(prof1))
        width, center = get_width_center_at_threshold(
            prof1, threshold, get_widest=True)
        center_xy.append(center)

    return center_xy


def get_width_center_at_threshold(
        profile, threshold, get_widest=True, force_above=False):
    """Get width and center of largest group in profile above threshold.

    Parameters
    ----------
    profile : np.array or list
        vector
    threshold : float
    get_widest : bool, optional
        True if ignore inner differences, just match first/last. Default is False
    force_above : bool, optional
        True if center_indexes locked to above threshold. Default is False.

    Returns
    -------
    width : float
        width of profile center values above or below threshold
        if failed -1
    center : float
        center position of center values above or below threshold
        if failed -1
    """
    width = None
    center = None

    if isinstance(profile, list):
        profile = np.array(profile)

    above = np.where(profile > threshold)
    if np.ma.is_masked(profile):
        below = np.ma.where(profile < threshold)
    else:
        below = np.where(profile < threshold)

    if len(above[0]) > 1 and len(below[0]) > 1:
        if above[0][0] > below[0][0] or force_above:
            center_indexes = above[0]
        else:
            center_indexes = below[0]

        if get_widest is False:
            first = center_indexes[0]
            last = center_indexes[-1]
        else:
            # find largest group, first/last index
            grouped_indexes = [0]
            for i in range(1, len(center_indexes)):
                if center_indexes[i] == center_indexes[i-1] + 1:
                    grouped_indexes.append(grouped_indexes[-1])
                else:
                    grouped_indexes.append(grouped_indexes[-1]+1)
            group_start = []
            group_size = []
            for i in range(grouped_indexes[-1]+1):
                group_start.append(center_indexes[
                    grouped_indexes.index(i)])
                group_size.append(grouped_indexes.count(i))
            largest_group = group_size.index(max(group_size))
            first = group_start[largest_group]
            last = first + group_size[largest_group] - 1

        if first == 0 or last == len(profile) - 1:
            width = None
            center = None
        else:
            # interpolate to find more exact width and center
            dy = profile[first] - threshold
            if profile[first] != profile[first-1]:
                dx = dy / (profile[first] - profile[first-1])
            else:
                dx = 0
            x1 = first - dx
            dy = profile[last] - threshold
            if profile[last] != profile[last+1]:
                dx = dy / (profile[last] - profile[last+1])
            else:
                dx = 0
            x2 = last + dx
            center = 0.5 * (x1+x2)
            width = x2 - x1
    elif len(above[0]) == 1 and len(below[0]) > 2:
        center = above[0][0]
    elif len(below[0]) == 1 and len(above[0]) > 2:
        center = below[0][0]

    return (width, center)


def optimize_center(image, mask_outer=0, max_from_part=4):
    """Find center and width of object in image.

    Parameters
    ----------
    image : np.2darray
    mask_outer : int, optional (float ok)
        Number of outer pixels to mask when searching. The default is 0.
    max_from_part : float, optional
        1/part of central image to find max from average

    Returns
    -------
    res : tuple of float or None
        center_x, center_y, widht_x, width_y
    """
    # get maximum profiles x and y
    mask_outer = round(mask_outer)
    if mask_outer == 0:
        prof_y = np.max(image, axis=1)
        prof_x = np.max(image, axis=0)
    else:
        prof_y = np.max(image[mask_outer:-mask_outer, mask_outer:-mask_outer], axis=1)
        prof_x = np.max(image[mask_outer:-mask_outer, mask_outer:-mask_outer], axis=0)
    # get width at halfmax and center for profiles
    max_from_part = round(max_from_part)
    if max_from_part == 0:
        max_from_part = 1
    width_x, center_x = get_width_center_at_threshold(
        prof_x, 0.5 * (
            np.mean(prof_x[prof_x.size//max_from_part:-prof_x.size//max_from_part])
            + min(prof_x)
            ),
        get_widest=True, force_above=True)
    width_y, center_y = get_width_center_at_threshold(
        prof_y, 0.5 * (
            np.mean(prof_y[prof_y.size//max_from_part:-prof_y.size//max_from_part])
            + min(prof_y)
            ),
        get_widest=True, force_above=True)
    if width_x is not None and width_y is not None:
        center_x += mask_outer
        center_y += mask_outer
        res = (center_x, center_y, width_x, width_y)
    else:
        res = None

    return res


def find_center_object(image, mask_outer=0, tolerances_width=[None, None], sigma=0):
    """Find center and width of object in image (high or low signal).

    Parameters
    ----------
    image : np.2darray
    mask_outer : int, optional (float ok)
        Number of outer pixels to mask when searching. The default is 0.
    tolerances_width : list of float or None
        min max acceptable widths to accept result and break loop
    sigma : float, options
        smooth by gaussian filter before finding center.
        NB - might drag signal to one side

    Returns
    -------
    res : tuple of float or None
        center_x, center_y, widht_x, width_y
    """
    res = None
    mask_outer = round(mask_outer)
    smoothed_image = gaussian_filter(image, sigma=sigma)
    # get min and max profiles x and y
    for getmax in [True, False]:
        if mask_outer == 0:
            if getmax:
                prof_y = np.max(smoothed_image, axis=1)
                prof_x = np.max(smoothed_image, axis=0)
            else:
                prof_y = np.min(smoothed_image, axis=1)
                prof_x = np.min(smoothed_image, axis=0)
        else:
            if getmax:
                prof_y = np.max(
                    smoothed_image[mask_outer:-mask_outer, mask_outer:-mask_outer],
                    axis=1)
                prof_x = np.max(
                    smoothed_image[mask_outer:-mask_outer, mask_outer:-mask_outer],
                    axis=0)
            else:
                prof_y = np.min(
                    smoothed_image[mask_outer:-mask_outer, mask_outer:-mask_outer],
                    axis=1)
                prof_x = np.min(
                    smoothed_image[mask_outer:-mask_outer, mask_outer:-mask_outer],
                    axis=0)
        # get width at halfmax and center for profiles
        width_x, center_x = get_width_center_at_threshold(
            prof_x, 0.5 * (np.mean(prof_x) + min(prof_x)),
            force_above=getmax)
        width_y, center_y = get_width_center_at_threshold(
            prof_y, 0.5 * (np.mean(prof_y) + min(prof_y)),
            force_above=getmax)
        if width_x is not None and width_y is not None:
            center_x += mask_outer
            center_y += mask_outer
            proceed = True
            if tolerances_width[0] is not None:
                if width_x < tolerances_width[0] or width_y < tolerances_width[0]:
                    proceed = False
            if tolerances_width[1] is not None:
                if width_x > tolerances_width[1] or width_y > tolerances_width[1]:
                    proceed = False
            if proceed:
                res = (center_x, center_y, width_x, width_y)
                break
    return res


def ESF_to_LSF(ESF, prefilter_sigma):
    """Calculate LSF spread function from edge spread function.

    Parameters
    ----------
    ESF : np.1darray
    prefilter_sigma : float
        gaussian filter to be corrected when gaussian MTF is used

    Returns
    -------
    LSF : np.1darray
        line spread function after gaussian filter - for gaussian fit
    LSF_not_filtered : np.1darray
        line spread function without gaussian prefilter - for discrete MTF
    ESF_filtered : np.1darray
        ESF gaussian smoothed
    """
    values_f = gaussian_filter(ESF, sigma=prefilter_sigma)
    LSF = np.diff(values_f)
    LSF_not_filtered = np.diff(ESF)
    if np.abs(np.min(LSF)) > np.abs(np.max(LSF)):  # ensure positive gauss
        LSF = -1. * LSF
        LSF_not_filtered = -1. * LSF_not_filtered

    return (LSF, LSF_not_filtered, values_f)


def cut_and_fade_LSF(profile, center=0, fwhm=0, cut_width=0, fade_width=0):
    """Cut and fade profile fwhm from center to reduce noise in LSF.

    Parameters
    ----------
    profile : list of float
    center : float
        center pos in pix
    fwhm : float
        fwhm in pix
    cut_width : float
        cut profile cut_width*fwhm from halfmax. If zero, also fade width ignored.
    fade_width : float (or None)
        fade profile to background fade*fwhm inside cut_width

    Returns
    -------
    modified_profile : list of float
    cut_dist_pix : float
        distance from center where profile is cut (unit = pix)
    fade_dist_pix : float
        distance from center where profile starts fading (unit = pix)
    """
    modified_profile = profile
    n_fade = 0
    if cut_width > 0:
        cut_width += 0.5  # from halfmax = 0.5 fwhm
        dx = cut_width*fwhm
        first_x = max(round(center - dx), 0)
        last_x = min(round(center + dx), len(profile) - 1)
        if fade_width is None:
            fade_width = 0
        if fade_width > 0:
            fade_width = min(fade_width, cut_width)
            n_fade = round(fade_width*fwhm)
            first_fade_x = first_x + n_fade
            last_fade_x = last_x - n_fade
            nn = first_fade_x - first_x
            gradient = np.multiply(
                np.arange(nn)/nn, profile[first_x:first_fade_x])
            modified_profile[first_x:first_fade_x] = gradient
            nn = last_x - last_fade_x
            gradient = np.multiply(
                np.flip(np.arange(nn)/nn), profile[last_fade_x:last_x])
            modified_profile[last_fade_x:last_x] = gradient
        if first_x > 0:
            modified_profile[0:first_x] = 0
        if last_x < len(profile) - 2:
            modified_profile[last_x:] = 0

    return (modified_profile, dx, dx - n_fade)


def rotate_point(xy, rotation_axis_xy, angle):
    """Rotate xy around origin_xy by an angle.

    Parameters
    ----------
    xy : tuple of floats
        coordinates to rotate
    rotation_axis_xy: tuple of floats
        coordinate of origin
    angle : float
        rotation angle in degrees

    Returns
    -------
    new_x : float
        rotated x
    new_y : float
        rotated y
    """
    xr, yr = rotation_axis_xy
    x, y = xy
    rad_angle = np.deg2rad(angle)
    new_x = xr + np.cos(rad_angle) * (x - xr) - np.sin(rad_angle) * (y - yr)
    new_y = yr + np.sin(rad_angle) * (x - xr) + np.cos(rad_angle) * (y - yr)
    return (new_x, new_y)


def rotate2d_offcenter(array2d, angle, offcenter):
    """Rotate 2d array around offcenter position.

    from stackoverflow.com/questions/25458442/
    rotate-a-2d-image-around-specified-origin-in-python

    Parameters
    ----------
    array2d : np.array
        Array to rotate
    angle : int
        Rotation angle.
    offcenter : tuple of ints
        (x, y) relative to image(array) center

    Returns
    -------
    rotated_2darray : np.array
    """
    arrshape = array2d.shape
    center = (offcenter[0] + arrshape[1] // 2, offcenter[1] + arrshape[0] // 2)
    pad_x = [arrshape[1] - round(center[0]), round(center[0])]
    pad_y = [arrshape[0] - round(center[1]), round(center[1])]
    try:
        padded_image = np.pad(array2d, [pad_y, pad_x], 'constant')
        rotated_padded = rotate(padded_image, angle, reshape=False)
        rotated_2darray = rotated_padded[pad_y[0]:-pad_y[1], pad_x[0]:-pad_x[1]]
    except ValueError:  # TODO errmsg (e.g. negative pad_width )
        rotated_2darray = array2d

    return rotated_2darray


def get_curve_values(x, y, y_values, force_first_below=False):
    """Lookup interpolated x values given y values.

    Parameters
    ----------
    x : array like of float
    y : array like of float
    y_values : array like of float
        input y values to calculate corresponding x values. The default is None.
    force_first_below : bool, optional
        return first x-value where y below given y_value. Default is False.

    Returns
    -------
    result_values : list of float
        corresponding values of input values
    """
    def get_interpolated_x(y_value, x1, x2, y1, y2):
        w = (y_value - y2) / (y1 - y2)
        return w * x1 + (1 - w) * x2

    result_values = []
    for yval in y_values:
        idx_above = np.where(y >= yval)
        idx_below = np.where(y < yval)
        try:
            idxs = [
                idx_below[0][0], idx_below[0][-1], idx_above[0][0], idx_above[0][-1]]
            idxs.sort()
            first = idxs[1]
            last = idxs[2]
            if first + 1 == last:
                result_values.append(
                    get_interpolated_x(yval, x[first], x[last], y[first], y[last]))
            else:
                if force_first_below:
                    result_values.append(x[idx_below[0][0]])
                else:
                    result_values.append(None)
        except IndexError:
            result_values.append(None)

    return result_values


def resample(input_y, input_x, step, first_step=0, n_steps=None):
    """Resample input_y with regular step.

    Parameters
    ----------
    input_y : array like of float
    input_x : array like of float
        assumed to be sorted
    step : float
        resulting step size of x
    first_step : float
        first value of x to output
    n_steps : int, optional
        number of values in new_x / new_y

    Returns
    -------
    new_x : np.array of float
    new_y : np.array of float
    """
    input_y = np.array(input_y)
    input_x = np.array(input_x)
    if n_steps is None:
        n_steps = (np.max(input_x) - first_step) // step
    new_x = step * np.arange(n_steps) + first_step
    new_y = np.interp(new_x, input_x, input_y)

    return (new_x, new_y)


def resample_by_binning(input_y, input_x, step, bin_size=None,
                        first_step=0, n_steps=None):
    """Resample input_y with regular step.

    Binning -slower than resample method, but smoother because averaging over step size.
    Use if step size might be larger than original.

    Parameters
    ----------
    input_y : array like of float
    input_x : array like of float
        assumed to be sorted
    step : float
        resulting step size of x
    bin_size : float
        bin_size for avaraging
    first_step : float
        first value of x to output
    n_steps : int, optional
        number of values in new_x / new_y

    Returns
    -------
    new_x : np.array of float
    new_y : np.array of float
    """
    input_y = np.array(input_y)
    input_x = np.array(input_x)
    if n_steps is None:
        n_steps = (np.max(input_x) - first_step) // step
    new_x = step * np.arange(n_steps) + first_step
    new_y = []
    if bin_size is None:
        bin_size = step
    n_values_this = []
    for this_x in new_x:
        values_this = input_y[np.logical_and(
            input_x >= this_x - 0.5*bin_size,
            input_x <= this_x + 0.5*bin_size)]
        if values_this.size > 0:
            new_y.append(np.nanmean(values_this))
        else:
            new_y.append(np.nan)
        n_values_this.append(values_this.size)
    new_y = np.array(new_y)

    def nan_helper(y):
        return np.isnan(y), lambda z: z.nonzero()[0]

    nans, x = nan_helper(new_y)
    new_y[nans] = np.interp(x(nans), x(~nans), new_y[~nans])

    return (new_x, new_y)


def get_min_max_pos_2d(image, roi_array):
    """Get position of first min and max value in image.

    Parameters
    ----------
    image : np.array
    roi_array : np.array
        dtype bool

    Returns
    -------
    list
        min_idx, max_idx
    """
    arr = np.ma.masked_array(image, mask=np.invert(roi_array))
    min_idx = np.where(arr == np.min(arr))
    max_idx = np.where(arr == np.max(arr))

    return [
        [min_idx[0][0], min_idx[1][0]],
        [max_idx[0][0], max_idx[1][0]]
        ]

def get_offset_max_pos_2d(image, roi_array, pixelsize):
    """Get offset (from image center) for max position, masked by ROI.

    Parameters
    ----------
    image : np.array
    roi_array : np.array
        dtype bool
    pixelsize : float

    Returns
    -------
    dx_mm : float
    dy_mm : float
        offset from image center in mm for max in image
    """
    arr = np.ma.masked_array(image, mask=np.invert(roi_array))
    max_idx = np.where(arr == np.max(arr))

    dx_mm = pixelsize * (max_idx[1][0] - image.shape[1] // 2)
    dy_mm = pixelsize * (max_idx[0][0] - image.shape[0] // 2)

    return (dx_mm, dy_mm)


def topolar(img, order=1):
    """
    Transform img to its polar coordinate representation.

    based on code from Matt Hancock
    https://stackoverflow.com/questions/3798333/image-information-along-a-polar-coordinate-system

    order: int, default 1
        Specify the spline interpolation order.
        High orders may be slow for large images.
    """
    # max_radius is the length of the diagonal from a corner to the mid-point of img.
    max_radius = 0.5*np.linalg.norm(img.shape)

    def transform(coords):
        # Put coord[1] in the interval, [-pi, pi]
        theta = 2*np.pi*coords[1] / (img.shape[1] - 1.)

        # Then map it to the interval [0, max_radius].
        # radius = float(img.shape[0]-coords[0]) / img.shape[0] * max_radius
        radius = max_radius * coords[0] / img.shape[0]

        i = 0.5*img.shape[0] - radius*np.sin(theta)
        j = radius*np.cos(theta) + 0.5*img.shape[1]
        return i, j

    polar = geometric_transform(img, transform, order=order)

    rads = max_radius * np.linspace(0, 1, img.shape[0])
    angs = np.linspace(0, 2*np.pi, img.shape[1])

    return polar, (rads, angs)


def masked_convolve2d(in1, in2, correct_missing=True, norm=True,
                      valid_ratio=1./3., *args, **kwargs):
    """Workaround for np.ma.MaskedArray in scipy.signal.convolve.

    From:
    https://stackoverflow.com/questions/38318362/2d-convolution-in-python-with-missing-data
    Converts the masked values to complex values=1j.
    The complex space allows to set a limit for the imaginary convolution.
    The function use a ratio `valid_ratio` of np.sum(in2) to
    set a lower limit on the imaginary part to mask the values.
    I.e. in1=[[1.,1.,--,--]] in2=[[1.,1.]]
     -> imaginary_part/sum(in2): [[1., 1., .5, 0.]]
     -> valid_ratio=.5 -> out:[[1., 1., .5, --]].

    Parameters
    ----------
    in1 : array_like
        First input.
    in2 : array_like
        Second input. Should have the same number of dimensions as `in1`.
    correct_missing : bool, optional
        correct the value of the convolution as a sum over valid data only,
        as masked values account 0 in the real space of the convolution.
    norm : bool, optional
        if the output should be normalized to np.sum(in2).
    valid_ratio: float, optional
        the upper limit of the imaginary convolution to mask values.
        Defined by the ratio of np.sum(in2).
    *args, **kwargs: optional
        parsed to scipy.signal.convolve(..., *args, **kwargs)
    """
    if not isinstance(in1, np.ma.MaskedArray):
        in1 = np.ma.array(in1)

    # np.complex128 -> stores real as np.float64
    con = convolve2d(
        in1.astype(np.complex128).filled(fill_value=1j),
        in2.astype(np.complex128), *args, **kwargs
        )

    # split complex128 to two float64s
    con_imag = con.imag
    con = con.real
    mask = np.abs(con_imag/np.sum(in2)) > valid_ratio

    # con_east.real / (1. - con_east.imag): correction,
    #   to get the mean over all valid values
    # con_east.imag > percent: how many percent of the single convolution
    #   value have to be from valid values
    if correct_missing:
        correction = np.sum(in2) - con_imag
        con[correction != 0] *= np.sum(in2) / correction[correction != 0]

    if norm:
        con /= np.sum(in2)

    return np.ma.array(con, mask=mask)