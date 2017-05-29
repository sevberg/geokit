from .util import *
from .srsutil import *

####################################################################
# INTERNAL FUNCTIONS

# Basic Loader
def loadRaster(x):
    """
    ***GeoKit INTERNAL***
    Load a raster dataset from various sources.
    """
    if(isinstance(x,str)):
        ds = gdal.Open(x)
    else:
        ds = x

    if(ds is None):
        raise GeoKitRasterError("Could not load input dataSource: ", str(x))
    return ds


# GDAL type mapper
_gdalIntToType = dict((v,k) for k,v in filter(lambda x: "GDT_" in x[0], gdal.__dict__.items()))
_gdalType={bool:"GDT_Byte", int:"GDT_Int32", float:"GDT_Float64","bool":"GDT_Byte", 
           "int8":"GDT_Byte", "int16":"GDT_Int16", "int32":"GDT_Int32", 
           "int64":"GDT_Int32", "uint8":"GDT_Byte", "uint16":"GDT_UInt16", 
           "uint32":"GDT_UInt32", "float32":"GDT_Float32", "float64":"GDT_Float64"}
def gdalType(s):
    """Try to determine gdal datatype from the given input type"""
    if( isinstance(s,str) ):
        if( hasattr(gdal, s)): return s
        elif( s.lower() in _gdalType): return _gdalType[s.lower()]
        elif( hasattr(gdal, 'GDT_%s'%s)): return 'GDT_%s'%s
        elif( s == "float" or s=="int" or s=="bool" ): return gdalType( np.dtype(s) )
    
    elif( isinstance(s,int) ): return _gdalIntToType[s] # If an int is given, it's probably
                                                        #  the GDAL type indicator (and not a 
                                                        #  sample data value)
    elif( isinstance(s,np.dtype) ): return gdalType(str(s))
    elif( isinstance(s,np.generic) ): return gdalType(s.dtype)
    elif( s is bool ): return _gdalType[bool]
    elif( s is int ): return _gdalType[int]
    elif( s is float ): return _gdalType[float]
    elif( isinstance(s,Iterable) ): return gdalType( s[0] )
    raise GeoKitRasterError("GDAL type could not be determined")  

# raster stat calculator
def calculateStats( source ):
    """GeoKit INTERNAL: Calculates the statistics of a raster and writes results into the raster
    * Assumes that the raster is writable
    """
    if isinstance(source,str):
        source = gdal.Open(source, 1)
    if source is None:
        raise GeoKitRasterError("Failed to open source: ", source)

    band = source.GetRasterBand(1)
    band.ComputeBandStats(0)
    band.ComputeRasterMinMax(0)


####################################################################
# Raster writer
def createRaster( bounds, output=None, pixelWidth=100, pixelHeight=100, dtype=None, srs='europe_m', compress=True, noData=None, overwrite=False, fill=None, data=None, **kwargs):
    """
    Create a raster file

    !NOTE! Raster datasets are always written in the 'yAtTop' orientation. Meaning that the first row of data values 
           (either written to or read from the dataset) will refer to the TOP of the defined boundary, and will then 
           move downward from there

    * If a data matrix is given, and a negative pixelWidth is defined, the data will be flipped automatically

    Return: None or gdal raster dataset (depending on whether an output path is given)

    Keyword inputs:
        bounds : The geographic extents spanned by the raster
            - (xMin, yMix, xMax, yMax)
            - geokit.Extent object
        
        output : A path to an output file 
            - string
            * If output is None, the raster will be created in memory and a dataset handel will be returned
            * If output is given, the raster will be written to disk and nothing will be returned
        
        pixelWidth : The pixel width of the raster in units of the input srs
            - float
            * The keyword 'dx' can be used as well and will override anything given assigned to 'pixelWidth'
        
        pixelHeight : The pixel height of the raster in units of the input srs
            - float
            * The keyword 'dy' can be used as well and will override anything given assigned to 'pixelHeight'

        dtype : The datatype of the represented by the created raster's band
            - string
            * Options are: Byte, Int16, Int32, Int64, Float32, Float64
            * If dtype is None and data is None, the assumed datatype is a 'Byte'
            * If dtype is None and data is not None, the datatype will be inferred from the given data
        
        srs : The Spatial reference system to apply to the created raster
            - osr.SpatialReference object
            - an EPSG integer ID
            - a string corresponding to one of the systems found in geokit.srs.SRSCOMMON
            - a WKT string
            * If 'bounds' is an Extent object, the bounds' internal srs will override the 'srs' input

        compress :  A flag instructing the output raster to use a compression algorithm
            - True/False
            * only useful if 'output' has been defined
            * "DEFLATE" used for Linux/Mac, "LZW" used for windows
        
        noData : Specifies which value should be considered as 'no data' in the created raster
            - numeric
            * Must be the same datatye as the 'dtype' input (or that which is derived)

        fill : The initial value given to all pixels in the created raster band
            - numeric
            * Must be the same datatye as the 'dtype' input (or that which is derived)

        overwrite : A flag to overwrite a pre-existing output file
            - True/False

        data : A 2D matrix to write into the resulting raster
            - np.ndarray
            * array dimensions must fit raster dimensions!!
    """

    # Fix some inputs for backwards compatibility
    pixelWidth = kwargs.pop("dx",pixelWidth)
    pixelHeight = kwargs.pop("dy",pixelHeight)
    fillValue = kwargs.pop("fillValue",fill)
    noDataValue = kwargs.pop("noDataValue",noData)

    # Check for existing file
    if(not output is None):
        if( os.path.isfile(output) ):
            if(overwrite==True):
                #print( "Removing existing raster file - " + output )
                os.remove(output)
                if(os.path.isfile(output+".aux.xml")):
                    os.remove(output+".aux.xml")
            else:
                raise GeoKitRasterError("Output file already exists: %s" %output)

    # Calculate axis information
    try: # maybe the user passed in an Extent object, test for this...
        xMin, yMin, xMax, yMax = bounds 
    except TypeError:
        xMin, yMin, xMax, yMax = bounds.xyXY
        srs = bounds.srs

    cols = round((xMax-xMin)/pixelWidth) # used 'round' instead of 'int' because this matched GDAL behavior better
    rows = round((yMax-yMin)/abs(pixelHeight))
    originX = xMin
    originY = yMax # Always use the "Y-at-Top" orientation
    
    # Get DataType
    if( not dtype is None): # a dtype was given, use it!
        dtype = gdalType( dtype )
    elif (not data is None): # a data matrix was give, use it's dtype! (assume a numpy array or derivative)
        dtype = gdalType( data.dtype )
    else: # Otherwise, just assume we want a Byte
        dtype = "GDT_Byte"
        
    # Open the driver
    if(output is None):
        driver = gdal.GetDriverByName('Mem') # create a raster in memory
        raster = driver.Create('', cols, rows, 1, getattr(gdal,dtype))
    else:
        opts = []
        if (compress):
            if( "win" in sys.platform):
                opts = ["COMPRESS=LZW"]
            else:   
                opts = ["COMPRESS=DEFLATE"]
        driver = gdal.GetDriverByName('GTiff') # Create a raster in storage
        raster = driver.Create(output, cols, rows, 1, getattr(gdal, dtype), opts)

    if(raster is None):
        raise GeoKitRasterError("Failed to create raster")

    raster.SetGeoTransform((originX, abs(pixelWidth), 0, originY, 0, -1*abs(pixelHeight)))
    #raster.SetGeoTransform((originX, abs(pixelWidth), 0, originY, 0, pixelHeight))
    
    # Set the SRS
    if not srs is None:
        rasterSRS = loadSRS(srs)
        raster.SetProjection( rasterSRS.ExportToWkt() )

    # Fill the raster will zeros, null values, or initial values (if given)
    band = raster.GetRasterBand(1)

    if( not noDataValue is None):
        band.SetNoDataValue(noDataValue)
        if fillValue is None and data is None:
            band.Fill(noDataValue)

    if( data is None ):
        if fillValue is None:
            band.Fill(0)
        else:
            band.Fill(fillValue)
            #band.WriteArray( np.zeros((rows,cols))+fillValue )
    else:
        # make sure dimension size is good
        if not (data.shape[0]==rows and data.shape[1]==cols):
            raise GeoKitRasterError("Raster dimensions and input data dimensions do not match")
        
        # See if data needs flipping
        if pixelHeight<0:
            data=data[::-1,:]

        # Write it!
        band.WriteArray( data )

    band.FlushCache()
    raster.FlushCache()

    # Return raster if in memory
    if ( output is None): 
        return raster

    # Calculate stats if data was given
    if(not data is None): 
        calculateStats(raster)
    
    return

####################################################################
# Fetch the raster as a matrix
def fetchMatrix(source, xOff=0, yOff=0, xWin=None, yWin=None ):
    """Fetch all or part of a raster's band as a numpy matrix
    
    * Unless one is trying to get the entire matrix from the raster dataset, usage of this function requires 
      intimate knowledge of the raster's characteristics. In this case it probably easier to use Extent.extractMatrix

    Inputs:
        source : The raster datasource
            - str -- A path on the filesystem 
            - gdal Dataset

        xOff - int : The index offset in the x-dimension

        yOff - int : The index offset in the y-dimension

        xWin - int : The window size in the x-dimension

        yWin - int : The window size in the y-dimension
    """

    sourceDS = loadRaster(source) # BE sure we have a raster
    sourceBand = sourceDS.GetRasterBand(1) # get band

    # set kwargs
    kwargs={}
    kwargs["xoff"] = xOff
    kwargs["yoff"] = yOff
    if not xWin is None: kwargs["win_xsize"] = xWin
    if not yWin is None: kwargs["win_ysize"] = yWin

    # get Data
    return sourceBand.ReadAsArray(**kwargs)

# Cutline fetcher
cutlineInfo = namedtuple("cutlineInfo","data info")
def fetchCutline(source, geom, cropToCutline=True, **kwargs):
    """Fetch a cutout of a raster source's data which is within a given geometry 

    Inputs:
        source : The raster datasource
            - str -- A path on the filesystem 
            - gdal Dataset

        geom : The geometry overwhich to cut out the raster's data
            - ogr Geometry object
            * Must be a Polygon or MultiPolygon

        cropToCutline : A flag which restricts the bounds of the returned matrix to that which most closely matches 
                        the geometry
            - True/False

        **kwargs
            * All kwargs are passes on to a call to gdal.Warp
            * See gdal.WarpOptions for more details
            * For example, 'allTouched' may be useful

    Returns:
        ( matrix-data, a rasterInfo output in the context of the created matrix )
    """
    # make sure we have a polygon or multipolygon geometry
    if not isinstance(geom, ogr.Geometry):
        raise GeoKitGeomError("Geom must be an OGR Geometry object")
    if not geom.GetGeometryName() in ["POLYGON","MULTIPOLYGON"]:
        raise GeoKitGeomError("Geom must be a Polygon or MultiPolygon type")

    # make geom into raster srs
    source = loadRaster(source)
    rInfo = rasterInfo(source)

    if not geom.GetSpatialReference().IsSame(rInfo.srs):
        geom.TransformTo(rInfo.srs)

    # make a quick vector dataset
    t = TemporaryDirectory()
    vecName = quickVector(geom,output=os.path.join(t.name,"tmp.shp"))
    
    # Do cutline
    cutName = os.path.join(t.name,"cut.tif")
    
    cutDS = gdal.Warp(cutName, source, cutlineDSName=vecName, cropToCutline=cropToCutline, **kwargs)
    cutDS.FlushCache()

    cutInfo = rasterInfo(cutDS)

    # Almost Done!
    returnVal = cutlineInfo(fetchMatrix(cutDS), cutInfo)

    # cleanup
    t.cleanup()

    # Now Done!
    return returnVal

def stats( source, geom=None, ignoreValue=None, **kwargs):
    """Compute some basic statistics of the values contained in a raster dataset.

    * Can clip the raster with a geometry
    * Can ignore certain values if the raster doesnt have a no-data-value
    * All kwargs are passed on to 'fetchCutline' when a 'geom' input is given
    """

    source = loadRaster(source)

    # Get the matrix to calculate over
    if geom is None:
        rawData = fetchMatrix(source)
        dataInfo = rasterInfo(source)
    else:
        rawData, dataInfo = fetchCutline(source, geom, **kwargs)

    # exclude nodata and ignore values
    sel = np.ones(rawData.shape, dtype='bool')

    if not ignoreValue is None:
        np.logical_and(rawData!= ignoreValue, sel,sel)


    if not dataInfo.noData is None:
        np.logical_and(rawData!= dataInfo.noData, sel,sel)

    # compute statistics
    data = rawData[sel].flatten()
    return describe(data)


####################################################################
# Gradient calculator
def gradient( source, mode ="total", factor=1, asMatrix=False, **kwargs):
    """Calculate a raster's gradient and return as a new dataset or simply a matrix

    Inputs:
        source
            str : A path to the raster dataset
            gdal.Dataset : A previously opened gdal raster dataset

        mode - "total"
            str : The mode to use when calculating
                * Options are....
                    "total" - Calculates the absolute gradient
                    "slope" - Same as 'total'
                    "north-south" - Calculates the "north-facing" gradient (negative numbers indicate a south facing gradient)
                    "ns" - Same as 'north-south'
                    "east-west" - Calculates the "east-facing" gradient (negative numbers indicate a west facing gradient)
                    "ew" - Same as 'east-west'
                    "dir" - calculates the gradient's direction

        !!!!!!!!!!FILL IN THE REST LATER!!!!!!!
    """
    # Make sure source is a source
    source = loadRaster(source)

    # Check mode
    acceptable = ["total", "slope", "north-south" , "east-west", 'dir', "ew", "ns"]
    if not ( mode in acceptable):
        raise ValueError("'mode' not understood. Must be one of: ", acceptable)

    # Get the factor
    sourceInfo = rasterInfo(source)
    if factor == "latlonToM":
        lonMid = (sourceInfo.xMax + sourceInfo.xMin)/2
        latMid = (sourceInfo.yMax + sourceInfo.yMin)/2
        R_EARTH = 6371000
        DEGtoRAD = np.pi/180

        yFactor = R_EARTH*DEGtoRAD # Get arc length in meters/Degree
        xFactor = R_EARTH*DEGtoRAD*np.cos(latMid*DEGtoRAD) # ditto...
    else:
        try:
            xFactor, yFactor = factor
        except:
            yFactor = factor
            xFactor = factor

    # Calculate gradient
    arr = fetchMatrix(source)
    
    if mode in ["north-south", "ns", "total", "slope", "dir"]:
        ns = np.zeros(arr.shape)
        ns[1:-1,:] = (arr[2:,:] - arr[:-2,:])/(2*sourceInfo.dy*yFactor)
        if mode in ["north-south","ns"]: output=ns

    if mode in ["east-west", "total", "slope", "dir"]:
        ew = np.zeros(arr.shape)
        ew[:,1:-1] = (arr[:,:-2] - arr[:,2:])/(2*sourceInfo.dx*xFactor)
        if mode in ["east-west","ew"]: output=ew
    
    if mode == "total" or mode == "slope":
        output = np.sqrt(ns*ns + ew*ew)

    if mode == "dir":
        output = np.arctan2(ns,ew)

    # Done!
    if asMatrix: 
        return output
    else:
        return createRaster(bounds=sourceInfo.bounds, pixelWidth=sourceInfo.dx, pixelHeight=sourceInfo.dy, 
                            srs=sourceInfo.srs, data=output, **kwargs)


####################################################################
# Get Raster information
Info = namedtuple("Info","srs dtype flipY yAtTop bounds xMin yMin xMax yMax dx dy pixelWidth pixelHeight noData, xWinSize, yWinSize")
def rasterInfo(sourceDS):
    """Returns a named tuple of the input raster's information.
    

    Includes:
        srs - The spatial reference system (as an OGR object)
        dtype - The datatype (as an ????)
        flipY - A flag which indicates that the raster starts at the 'bottom' as opposed to at the 'top'
        bounds - The xMin, yMin, xMax, and yMax values as a tuple
        xMin, yMin, xMax, yMax - The individual boundary values
        pixelWidth, pixelHeight - The raster's pixelWidth and pixelHeight
        dx, dy - Shorthand names for pixelWidth (dx) and pixelHeight (dy)
        noData - The noData value used by the raster
    """
    output = {}
    sourceDS = loadRaster(sourceDS)

    # get srs
    srs = loadSRS( sourceDS.GetProjectionRef() )
    output['srs']=srs

    # get extent and resolution
    sourceBand = sourceDS.GetRasterBand(1)
    output['dtype'] = sourceBand.DataType
    output['noData'] = sourceBand.GetNoDataValue()
    
    
    xSize = sourceBand.XSize
    ySize = sourceBand.YSize

    xOrigin, dx, trash, yOrigin, trash, dy = sourceDS.GetGeoTransform()
    
    xMin = xOrigin
    xMax = xOrigin+dx*xSize

    if( dy<0 ):
        yMax = yOrigin
        yMin = yMax+dy*ySize
        dy = -1*dy
        output["flipY"]=True
        output["yAtTop"]=True
    else:
        yMin = yOrigin
        yMax = yOrigin+dy*ySize
        output["flipY"]=False
        output["yAtTop"]=False

    output['pixelWidth'] = dx
    output['pixelHeight'] = dy
    output['dx'] = dx
    output['dy'] = dy
    output['xMin'] = xMin
    output['xMax'] = xMax
    output['yMin'] = yMin
    output['yMax'] = yMax
    output['xWinSize'] = xSize
    output['yWinSize'] = ySize
    output['bounds'] = (xMin, yMin, xMax, yMax)

    # clean up 
    del sourceBand, sourceDS

    # return
    return Info(**output)

####################################################################
# Fetch specific points in a raster
def _pointGen(x,y,s):
    tmpPt = ogr.Geometry(ogr.wkbPoint)
    tmpPt.AddPoint(x, y)
    tmpPt.AssignSpatialReference(s)
    return tmpPt

def pointValues(source, points, pointSRS='latlon', winRange=0):
    """Extracts the value of a raster a a given point or collection of points. Can also extract a window of values if desired

    * If the given raster is not in the 'flipped-y' orientation, the result will be automatically flipped

    Returns a tuple consisting of: list of value-windows at each of the given points : a list of x and y offsets from the located index
        * If only a single point is given, it will still need to be accessed as the first element of the returned list
        * If a winRange of 0 is given, the actual value will still need to be accessed as the first column of the first row in the value-window
        * Offsets are in 'index' units

    Inputs:
        source
            str -- Path to an input shapefile
            * either source or wkt must be provided

        points
            [ogr-Point, ] -- An array of OGR point-geometry objects
            ogr-Point -- A single OGR point-geometry object
            (lon, lat) -- A single lattitude/longitude pair
            [ (lon, lat), ] -- A list of latitude longitude pairs

        winRange - (0)
            int -- The number of raster pixels to include around the located points
            * Result extends 'winRange' pixes in all directions, so a winRange of 0 will result in a returned a window of shape (1,1), a winRange of 1 will result in a returned window of shape (3,3), and so on...
    """
    # Be sure we have a raster and srs
    source = loadRaster(source)
    info = rasterInfo(source)
    pointSRS = loadSRS(pointSRS)

    # See if point is a point geometry array, if not make it into one
    if isinstance(points, ogr.Geometry):
        points = [points, ]

    elif isinstance( points, tuple ): # Check if points is a single location (as a tuple) 
        points = [_pointGen(points[0], points[1], pointSRS), ] # Assume tuple is (lon,lat)

    else: # Assume points is iterable
        try:
            points = [_pointGen(pt[0], pt[1], pointSRS) for pt in points] # first check for basic lat/lon
        except: 
            points = points # Assmume points is already an array of point geometries

    # Get point srs directly from the first point (also checks if we have an array of points)
    try:
        pointSRS = points[0].GetSpatialReference()
    except:
        raise GeoKitRasterError("Failed to load points")

    # Cast to source srs
    if not pointSRS.IsSame(info.srs):
        trx = osr.CoordinateTransformation(points[0].GetSpatialReference(), info.srs)
        for pt in points:
            pt.Transform(trx)
    
    # Get x/y values as numpy arrays
    x = np.array([pt.GetX() for pt in points])
    y = np.array([pt.GetY() for pt in points])
    
    # Calculate x/y indexes
    xValues = (x-(info.xMin+0.5*info.pixelWidth))/info.pixelWidth
    xIndexes = np.round( xValues )
    xOffset = xValues-xIndexes
    
    if info.yAtTop:
        yValues = ((info.yMax-0.5*info.pixelWidth)-y)/abs(info.pixelHeight)
        yIndexes = np.round( yValues )
        yOffset = yValues-yIndexes
    else:
        yValues = (y-(info.yMin+0.5*info.pixelWidth))/info.pixelHeight
        yIndexes = np.round( yValues )
        yOffset = -1*(yValues-yIndexes)
    

    offsets = list(zip(xOffset,yOffset))

    # Calculate the starts and window size
    xStarts = xIndexes-winRange
    yStarts = yIndexes-winRange
    window = 2*winRange+1

    if xStarts.min()<0 or yStarts.min()<0 or (xStarts.max()+window)>info.xWinSize or (yStarts.max()+window)>info.yWinSize:
        raise GeoKitRasterError("One of the given points (or extraction windows) exceeds the source's limits")

    # Read values
    values = []
    band = source.GetRasterBand(1)

    for xi,yi in zip(xStarts, yStarts):
        # Open and read from raster
        data = band.ReadAsArray(xoff=xi, yoff=yi, win_xsize=window, win_ysize=window)

        # flip if not in the 'flipped-y' orientation
        if not info.yAtTop:
            data=data[::-1,:]

        # Append to values
        values.append(data)

    # Done!
    return values, offsets

####################################################################
# Shortcut for getting just the raster value
def pointValue(source, point, pointSRS='latlon', mode='near', **kwargs):
    """Retrieve a single value for each point(s)

    Inputs:
        source
            str -- Path to a raster datasource
            gdal.Dataset -- A previously opened gdal raster dataset

        point
            (float,float) -- X and Y coordinates of the point to search for
            [(float, float),] -- A list of X and Y coordinates to search for
            ogr-Point-Geometry -- A search point as an OGR point geometry
            [ogr-Point-Geometry, ] -- A list of OGR point geomerties to search for
            * !REMEMBER! For lat and lon coordinates, X is lon and Y is lat 
              (opposite of what you may think...)

        pointSRS ('latlon') - Any recongnizable SRS identifier
            * Can use an EPSG number, a WKT string, an SRSCOMMOM member, or an already 
              open srs object
            * Default is latitude and longitude
        
        mode -- The interpolation scheme to use
            * options are...
                - "near" - Just gets the nearest value (this is default)
                - "linear-spline" - calculates a linear spline inbetween points
                - "cubic-spline" - calculates a cubic spline inbetween points
                - "average" - calculates average across a window
                - "func" - uses user-provided calculator

        Kwargs:
            winRange -- An integer window range to extract
                * Useful when using "average" or "func" mode to control the window size
                * Example: winRange=3 will extract 3 rows/columns away from the located point 
                  (creates a 7x7 matrix) 
            func -- A function which takes an NxN matrix as input, does a calculation
                    and returns a single scalar
                * Required when using the "func" interpolation mode
        
        """

    if mode=='near':
        # Simple get the nearest value
        result = pointValues(source, point, pointSRS=pointSRS, winRange=0)[0]

    elif mode=="linear-spline": # use a spline interpolation scheme
        # setup inputs
        win = 2
        x = np.linspace(-1*win,win,2*win+1)
        y = np.linspace(-1*win,win,2*win+1)

        # get raw data
        rasterData, offsets = pointValues(source, point, pointSRS=pointSRS, winRange=win)

        # Calculate interpolated values
        result=[]
        for z,pt in zip(rasterData,offsets):
            rbs = RectBivariateSpline(y,x,z, kx=1, ky=1)

            result.append(rbs(pt[1],pt[0]))

    elif mode=="cubic-spline": # use a spline interpolation scheme
        # setup inputs
        win = 4
        x = np.linspace(-1*win,win,2*win+1)
        y = np.linspace(-1*win,win,2*win+1)
        
        # Get raw data
        rasterData, offsets = pointValues(source, point, pointSRS=pointSRS, winRange=win)
        
        # Calculate interpolated values
        result=[]
        for z,pt in zip(rasterData,offsets):
            rbs = RectBivariateSpline(y,x,z)

            result.append(rbs(pt[1],pt[0]))

    elif mode == "average": # Get the average in a window
        win = kwargs.get("winRange",3)
        rasterData, offsets = pointValues(source, point, pointSRS=pointSRS, winRange=win)
        result = []
        for z,pt in zip(rasterData,offsets):
            result.append([[z.mean()]])

    elif mode == "func": # Use a general function processor
        if not "func" in kwargs:
            raise GeoKitRasterError("'func' mode chosen, but no func kwargs was given")
        win = kwargs.get("winRange",3)
        rasterData, offsets = pointValues(source, point, pointSRS=pointSRS, winRange=win)
        result = []
        for z,pt in zip(rasterData,offsets):
            result.append( kwargs["func"](z) )

        if len(result)==1: return result[0]
        else: return np.array(result)

    else:
        raise GeoKitRasterError("Interpolation mode not understood: ", mode)

    # Done!
    if len(result)==1: return result[0][0][0]
    else: return np.array([r[0][0] for r in result])
        
    
####################################################################
# General raster mutator
def mutateValues(source, processor=None, output=None, dtype=None, **kwargs):
    """
    Process a raster according to a given function

    Returns or creates a gdal dataset with the resulting data

    * If the user wishes to generate an output file (by giving an 'output' input), then nothing will be returned to help avoid dependance issues. If no output is provided, however, the function will return a gdal dataset for immediate use

    Inputs:
        source 
            str -- The path to the raster to processes
            gdal.Dataset -- The input data source as a gdal dataset object

        processor: (None) 
            func -- A function for processing the source data
            * The function will take single argument (a 2D numpy.ndarray) 
            * The function must return a numpy.ndarray of the same size as the input
            * The return type must also be containable within a Float32 (int and boolean is okay)
            * See example below for more info

        output: (None)
            str -- A path to a resulting output raster
            * Using None implies results are contained in memory
            * Not giving an output will cause the function to return a gdal dataset, otherwise it will return nothing
        
        kwargs: 
            * All kwargs are passed on to a call to createRaster, which is generating the resulting dataset
            * Do not provide the following inputs since they are defined in the function:
                - pixelHeight
                - pixelWidth
                - bounds
                - srs
                - data

    Example:
        If you wanted to assign suitability factors based on integer identifiers (like in the CLC dataset!)

        def calcSuitability( data ):
            # create an ouptut matrix
            outputMatrix = numpy.zeros( data.shape )

            # do the processing
            outputMatrix[ data == 1 ] = 0.1
            outputMatrix[ data == 2 ] = 0.2 
            outputMatrix[ data == 10] = 0.4
            outputMatrix[ np.logical_and(data > 15, data < 20)  ] = 0.5

            # return the output matrix
            return outputMatrix

        result = processRaster( <source-path>, processor=calcSuitability )
    """
    # open the dataset and get SRS
    workingDS = loadRaster(source)

    # Get ds info
    dsInfo = rasterInfo(workingDS)
    workingExtent = dsInfo.bounds

    # Read data into array
    sourceBand = workingDS.GetRasterBand(1)
    sourceData = sourceBand.ReadAsArray()

    # Perform processing
    processedData = processor( sourceData ) if processor else sourceData
    if(dtype and processedData.dtype!=dtype):
        processedData = processedData.astype(dtype)

    # Ensure returned matrix is okay
    if( processedData.shape != sourceData.shape ):
        raise GeoKitRasterError( "Processed matrix does not have the correct shape \nIs {0} \nShoud be {1}",format(rawSuitability.shape, sourceData.shape ))
    del sourceData

    # Check if flipping is required
    if not dsInfo.yAtTop:
        processedData = processedData[::-1,:]

    # Create an output raster
    outDS = createRaster( pixelHeight=dsInfo.dy, pixelWidth=dsInfo.dx, bounds=workingExtent, 
                          srs=dsInfo.srs, data=processedData, output=output, **kwargs )

    # Done!
    if(output is None):
        if(outDS is None): raise GeoKitRasterError("Error creating temporary working raster")
        outDS.FlushCache() # just for good measure

        return outDS
    else:
        calculateStats(output)
        return

def drawImage(data, bounds=None, ax=None, scaling=None, yAtTop=True, **kwargs):
    """Draw some data"""
    showPlot = False
    if ax is None:
        showPlot = True
        import matplotlib.pyplot as plt
        plt.figure(figsize=(12,12))
        ax = plt.subplot(111)

    # If bounds is none, make a boundary
    if bounds is None:
        xMin,yMin,xMax,yMax = 0,0,data.shape[1],data.shape[0] # bounds = xMin,yMin,xMax,yMax
    else:
        try:
            xMin,yMin,xMax,yMax = bounds
        except: # maybe bounds is an ExtentObject
            xMin,yMin,xMax,yMax = bounds.xyXY

    # Set extent
    extent = (xMin,xMax,yMin,yMax)
    
    # handle flipped data
    if not yAtTop: data=data[::-1,:]

    # Draw image
    if scaling: data=scaleMatrix(data,scaling,strict=False)
    h = ax.imshow( data, extent=extent, **kwargs)

    # Done!
    if showPlot:
        ax.set_aspect('equal')
        ax.autoscale(enable=True)
        plt.show()
    else:
        return h
