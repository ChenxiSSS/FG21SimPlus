# Copyright (c) 2016 Weitian LI <liweitianux@live.com>
# MIT license

"""
Diffuse Galactic free-free emission simulations.
"""

import os
import logging
from datetime import datetime, timezone

import numpy as np
from astropy.io import fits
import astropy.units as au
import healpy as hp

from ..utils import read_fits_healpix, write_fits_healpix


logger = logging.getLogger(__name__)


class FreeFree:
    """
    Simulate the diffuse Galactic free-free emission.

    The [Dickinson2003] method is followed to derive the free-free template.
    The H\alpha survey map [Finkbeiner2003] is first corrected for dust
    absorption using the infrared 100-\mu{}m dust map [Schlegel1998],
    and then converted to free-free emission map (brightness temperature).

    Parameters
    ----------
    configs : ConfigManager object
        An `ConfigManager` object contains default and user configurations.
        For more details, see the example config specification.

    Attributes
    ----------
    ???

    References
    ----------
    .. [Dickinson2003]
       Dickinson, C.; Davies, R. D.; Davis, R. J.,
       "Towards a free-free template for CMB foregrounds",
       2003, MNRAS, 341, 369,
       http://adsabs.harvard.edu/abs/2003MNRAS.341..369D

    .. [Finkbeiner2003]
       Finkbeiner, Douglas P.,
       "A Full-Sky Hα Template for Microwave Foreground Prediction",
       2003, ApJS, 146, 407,
       http://adsabs.harvard.edu/abs/2003ApJS..146..407F

    .. [Schlegel1998]
       Schlegel, David J.; Finkbeiner, Douglas P.; Davis, Marc,
       "Maps of Dust Infrared Emission for Use in Estimation of Reddening
       and Cosmic Microwave Background Radiation Foregrounds",
       1998, ApJ, 500, 525,
       http://adsabs.harvard.edu/abs/1998ApJ...500..525S
    """
    def __init__(self, configs):
        self.configs = configs
        self._set_configs()
        self._load_halphamap()
        self._load_dustmap()

    def _set_configs(self):
        """Load the configs and set the corresponding class attributes."""
        self.halphamap_path = self.configs.get_path(
            "galactic/freefree/halphamap")
        self.halphamap_unit = au.Unit(
            self.configs.getn("galactic/freefree/halphamap_unit"))
        self.dustmap_path = self.configs.get_path(
            "galactic/freefree/dustmap")
        self.dustmap_unit = au.Unit(
            self.configs.getn("galactic/freefree/dustmap_unit"))
        # output
        self.prefix = self.configs.getn("galactic/freefree/prefix")
        self.save = self.configs.getn("galactic/freefree/save")
        self.output_dir = self.configs.get_path(
            "galactic/freefree/output_dir")
        self.filename_pattern = self.configs.getn("output/filename_pattern")
        self.use_float = self.configs.getn("output/use_float")
        self.clobber = self.configs.getn("output/clobber")
        #
        self.nside = self.configs.getn("common/nside")
        self.freq_unit = au.Unit(self.configs.getn("frequency/unit"))
        #
        logger.info("Loaded and set up configurations")

    def _load_halphamap(self):
        """Load the H{\alpha} map, and upgrade/downgrade the resolution
        to match the output Nside.
        """
        self.halphamap, self.halphamap_header = read_fits_healpix(
            self.halphamap_path)
        halphamap_nside = self.halphamap_header["NSIDE"]
        logger.info("Loaded H[alpha] map from {0} (Nside={1})".format(
            self.halphamap_path, halphamap_nside))
        # TODO: Validate & convert unit
        if self.halphamap_unit != au.Unit("Rayleigh"):
            raise ValueError("unsupported Halpha map unit: {0}".format(
                self.halphamap_unit))
        # Upgrade/downgrade resolution
        if halphamap_nside != self.nside:
            self.halphamap = hp.ud_grade(self.halphamap, nside_out=self.nside)
            logger.info("Upgrade/downgrade H[alpha] map from Nside "
                        "{0} to {1}".format(halphamap_nside, self.nside))

    def _load_dustmap(self):
        """Load the dust map, and upgrade/downgrade the resolution
        to match the output Nside.
        """
        self.dustmap, self.dustmap_header = read_fits_healpix(
            self.dustmap_path)
        dustmap_nside = self.dustmap_header["NSIDE"]
        logger.info("Loaded dust map from {0} (Nside={1})".format(
            self.dustmap_path, dustmap_nside))
        # TODO: Validate & convert unit
        if self.dustmap_unit != au.Unit("MJy / sr"):
            raise ValueError("unsupported dust map unit: {0}".format(
                self.dustmap_unit))
        # Upgrade/downgrade resolution
        if dustmap_nside != self.nside:
            self.dustmap = hp.ud_grade(self.dustmap, nside_out=self.nside)
            logger.info("Upgrade/downgrade dust map from Nside "
                        "{0} to {1}".format(dustmap_nside, self.nside))

    def _correct_dust_absorption(self):
        """Correct the H{\alpha} map for dust absorption using the
        100-{\mu}m dust map.

        References: [Dickinson2003]: Eq.(1, 3); Sec.(2.5)
        """
        if hasattr(self, "dust_corrected") and self.dust_corrected:
            return
        #
        logger.info("Correct H[alpha] map for dust absorption")
        # Effective dust fraction in the LoS actually absorbing Halpha
        f_dust = 0.33
        logger.info("Effective dust fraction: {0}".format(f_dust))
        # NOTE:
        # Mask the regions where the true Halpha absorption is uncertain.
        # When the dust absorption goes rather large, the true Halpha
        # absorption can not well determined.
        # Therefore, the regions where the calculated Halpha absorption
        # greater than 1.0 mag are masked out.
        halpha_abs_th = 1.0  # Halpha absorption threshold, unit: [ mag ]
        # Corresponding dust absorption threshold, unit: [ MJy / sr ]
        dust_abs_th = halpha_abs_th / 0.0462 / f_dust
        logger.info("Dust absorption mask threshold: " +
                    "{0:.1f} MJy/sr ".format(dust_abs_th) +
                    "<-> H[alpha] absorption threshold: " +
                    "{0:.1f} mag".format(halpha_abs_th))
        mask = (self.dustmap > dust_abs_th)
        self.dustmap[mask] = np.nan
        fp_mask = 100 * mask.sum() / self.dustmap.size
        logger.warning("Dust map masked fraction: {0:.1f}%".format(fp_mask))
        #
        halphamap_corr = self.halphamap * 10**(self.dustmap * 0.0185 * f_dust)
        self.halphamap = halphamap_corr
        self.dust_corrected = True
        logger.info("Done dust absorption correction")

    def _calc_ratio_a(self, Te, nu_GHz):
        """Calculate the ratio factor a(T, nu), which will be used to
        transform the Halpha emission (Rayleigh) to free-free emission
        brightness temperature (mK).

        References: [Dickinson2003], Eq.(8)
        """
        term1 = 0.366 * nu_GHz**0.1 * Te**(-0.15)
        term2 = np.log(4.995e-2 / nu_GHz) + 1.5*np.log(Te)
        a = term1 * term2
        return a

    def _simulate_frequency(self, frequency):
        """Simulate the free-free map at the specified frequency.

        References: [Dickinson2003], Eq.(11)

        NOTE: [Dickinson2003], Eq.(11) may wrongly have the "10^3" term.
        """
        # Correct for dust absorption first
        self._correct_dust_absorption()
        # Assumed electron temperature [ K ]
        Te = 7000.0
        T4 = Te / 1e4
        nu = frequency * self.freq_unit.to(au.GHz)  # frequency [ GHz ]
        ratio_a = self._calc_ratio_a(Te, nu)
        # NOTE: ignored the "10^3" term in the referred equation
        ratio_mK_R = (8.396 * ratio_a * nu**(-2.1) *
                      T4**0.667 * 10**(0.029/T4) * (1+0.08))
        # Use "Kelvin" as the brightness temperature unit
        ratio_K_R = ratio_mK_R * au.mK.to(au.K)
        hpmap_f = self.halphamap * ratio_K_R
        return hpmap_f

    def _make_header(self):
        """Make the header with detail information (e.g., parameters and
        history) for the simulated products.
        """
        header = fits.Header()
        header["COMP"] = ("Galactic free-free emission",
                          "Emission component")
        header["CREATOR"] = (__name__, "File creator")
        # TODO:
        history = []
        comments = []
        for hist in history:
            header.add_history(hist)
        for cmt in comments:
            header.add_comment(cmt)
        self.header = header
        logger.info("Created FITS header")

    def output(self, hpmap, frequency):
        """Write the simulated free-free map to disk with proper header
        keywords and history.
        """
        if not os.path.exists(self.output_dir):
            os.mkdir(self.output_dir)
            logger.info("Created output dir: {0}".format(self.output_dir))
        #
        filename = self.filename_pattern.format(prefix=self.prefix,
                                                frequency=frequency)
        filename += ".fits"
        filepath = os.path.join(self.output_dir, filename)
        if not hasattr(self, "header"):
            self._make_header()
        header = self.header.copy()
        header["FREQ"] = (frequency, "Frequency [ MHz ]")
        header["DATE"] = (
            datetime.now(timezone.utc).astimezone().isoformat(),
            "File creation date"
        )
        if self.use_float:
            hpmap = hpmap.astype(np.float32)
        write_fits_healpix(filepath, hpmap, header=header,
                           clobber=self.clobber)
        logger.info("Write simulated map to file: {0}".format(filepath))

    def simulate(self, frequencies):
        """Simulate the free-free map at the specified frequencies."""
        hpmaps = []
        for f in np.array(frequencies, ndmin=1):
            logger.info("Simulating free-free map at {0} ({1}) ...".format(
                f, self.freq_unit))
            hpmap_f = self._simulate_frequency(f)
            hpmaps.append(hpmap_f)
            if self.save:
                self.output(hpmap_f, f)
        return hpmaps
